#!/usr/bin/env python3
"""Block on one event from a push source, then hand back one terminal receipt.

One process per wait. It attaches to the source first, prints an `armed`
acknowledgment, sends at most one optional snapshot request, and then blocks
until a matching terminal event arrives, the absolute deadline passes, the
source breaks, or the wait is cancelled. There is no polling: no repeated
snapshot, no status timer, no reconnect rescan.

The spec is data, never code. Selectors are field paths and literals, so an
untrusted producer payload can never become a command, and the wake command
is taken from the spec alone.

Exit codes:
    0  matched terminal event (wake delivered, or no wake armed)
    2  spec invalid
    3  deadline exceeded
    4  source error (connect, malformed frame, oversize frame, EOF)
    5  claim conflict (wait id or receipt path already owned)
    6  cancelled
    7  matched, but the armed wake failed to deliver

Usage:
    python3 wait_event.py --spec <path>
    python3 wait_event.py --spec -        # spec on stdin
"""
from __future__ import annotations

import argparse
import errno
import json
import os
import select
import signal
import socket
import stat
import subprocess
import sys
import time

SCHEMA_RECEIPT = "event-wait/receipt/v1"
SCHEMA_ARMED = "event-wait/armed/v1"

EXIT_MATCHED = 0
EXIT_SPEC_INVALID = 2
EXIT_TIMEOUT = 3
EXIT_SOURCE_ERROR = 4
EXIT_CLAIM_CONFLICT = 5
EXIT_CANCELLED = 6
EXIT_CALLBACK_FAILED = 7

DEFAULT_MAX_FRAME_BYTES = 1024 * 1024
HARD_MAX_FRAME_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_RECORD_BYTES = 64 * 1024
HARD_MAX_RECORD_BYTES = 1024 * 1024
HARD_MAX_DEADLINE_SECONDS = 86400.0
DEFAULT_WAKE_TIMEOUT_SECONDS = 30.0
HARD_MAX_WAKE_TIMEOUT_SECONDS = 300.0
MAX_SEEN_EVENT_IDS = 10000
READ_CHUNK_BYTES = 65536
WAIT_ID_MAX_LEN = 128
WAIT_ID_ALLOWED = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
)

MISSING = object()
WOULD_BLOCK = object()


class SpecError(Exception):
    """The spec is not usable. Carries a stable code and a redacted detail."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class ClaimError(Exception):
    """Another wait already owns this wait id or receipt path."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class SourceError(Exception):
    """The source could not be read. Detail never quotes producer bytes."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class Cancelled(Exception):
    """A termination signal reached this wait."""


class Timeout(Exception):
    """The absolute deadline passed."""


def _require_dict(value, where: str) -> dict:
    if not isinstance(value, dict):
        raise SpecError("spec_type", f"{where} must be an object")
    return value


def _reject_unknown(value: dict, allowed: tuple[str, ...], where: str) -> None:
    extra = sorted(set(value) - set(allowed))
    if extra:
        raise SpecError("spec_unknown_key", f"{where} has unknown keys: {extra}")


def _require_str(value, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise SpecError("spec_type", f"{where} must be a non-empty string")
    return value


def _require_path_list(value, where: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise SpecError("spec_type", f"{where} must be a non-empty list of keys")
    for key in value:
        if not isinstance(key, str) or not key:
            raise SpecError("spec_type", f"{where} entries must be non-empty strings")
    return list(value)


def _require_argv(value, where: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise SpecError("spec_type", f"{where} must be a non-empty argument list")
    for item in value:
        if not isinstance(item, str):
            raise SpecError("spec_type", f"{where} entries must be strings")
    return list(value)


def _require_abs_path(value, where: str) -> str:
    text = _require_str(value, where)
    if not os.path.isabs(text):
        raise SpecError("spec_path", f"{where} must be an absolute path")
    return text


def _require_number(value, where: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SpecError("spec_type", f"{where} must be a number")
    number = float(value)
    if not low < number <= high:
        raise SpecError("spec_range", f"{where} must be >{low} and <={high}")
    return number


def _require_match_fields(value, where: str) -> dict:
    fields = _require_dict(value, where)
    for key, want in fields.items():
        if not isinstance(key, str) or not key:
            raise SpecError("spec_type", f"{where} keys must be non-empty strings")
        if not isinstance(want, (str, int, float, bool)):
            raise SpecError("spec_type", f"{where} values must be scalars")
    return dict(fields)


def dig(record, path: list[str]):
    """Follow a literal key path into nested objects, or return MISSING."""
    current = record
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return MISSING
        current = current[key]
    return current


def envelope_matches(record: dict, fields: dict) -> bool:
    for key, want in fields.items():
        if record.get(key) != want:
            return False
    return True


def parse_framing(raw, where: str) -> dict:
    if raw is None:
        return {"kind": "lines"}
    framing = _require_dict(raw, where)
    kind = _require_str(framing.get("kind"), f"{where}.kind")
    if kind == "lines":
        _reject_unknown(framing, ("kind",), where)
        return {"kind": "lines"}
    if kind == "length_prefix":
        _reject_unknown(framing, ("kind", "prefix_bytes", "byte_order"), where)
        prefix_bytes = framing.get("prefix_bytes", 4)
        if prefix_bytes not in (2, 4, 8):
            raise SpecError("spec_range", f"{where}.prefix_bytes must be 2, 4 or 8")
        byte_order = framing.get("byte_order", "big")
        if byte_order not in ("big", "little"):
            raise SpecError("spec_range", f"{where}.byte_order must be big or little")
        return {
            "kind": "length_prefix",
            "prefix_bytes": int(prefix_bytes),
            "byte_order": byte_order,
        }
    raise SpecError("spec_range", f"{where}.kind must be lines or length_prefix")


def parse_envelope(raw, where: str) -> dict:
    if raw is None:
        return {"match_fields": {}, "body_path": []}
    envelope = _require_dict(raw, where)
    _reject_unknown(envelope, ("match_fields", "body_path"), where)
    match_fields = _require_match_fields(envelope.get("match_fields", {}), f"{where}.match_fields")
    body_raw = envelope.get("body_path")
    body_path = [] if body_raw is None else _require_path_list(body_raw, f"{where}.body_path")
    return {"match_fields": match_fields, "body_path": body_path}


def parse_snapshot(raw, where: str) -> dict | None:
    if raw is None:
        return None
    snapshot = _require_dict(raw, where)
    _reject_unknown(
        snapshot,
        (
            "request",
            "request_id_field",
            "request_id_value",
            "response_match_fields",
            "error_match_fields",
            "body_path",
        ),
        where,
    )
    request = _require_dict(snapshot.get("request"), f"{where}.request")
    request_id_field = snapshot.get("request_id_field")
    if request_id_field is not None:
        request_id_field = _require_str(request_id_field, f"{where}.request_id_field")
    request_id_value = snapshot.get("request_id_value")
    if request_id_value is not None:
        request_id_value = _require_str(request_id_value, f"{where}.request_id_value")
    response_match = _require_match_fields(
        snapshot.get("response_match_fields", {}), f"{where}.response_match_fields"
    )
    if not response_match:
        raise SpecError(
            "spec_range", f"{where}.response_match_fields must name at least one field"
        )
    error_match = _require_match_fields(
        snapshot.get("error_match_fields", {}), f"{where}.error_match_fields"
    )
    body_raw = snapshot.get("body_path")
    body_path = [] if body_raw is None else _require_path_list(body_raw, f"{where}.body_path")
    return {
        "request": dict(request),
        "request_id_field": request_id_field,
        "request_id_value": request_id_value,
        "response_match_fields": response_match,
        "error_match_fields": error_match,
        "body_path": body_path,
    }


def parse_source(raw) -> dict:
    source = _require_dict(raw, "source")
    kind = _require_str(source.get("kind"), "source.kind")
    if kind == "unix_socket":
        _reject_unknown(
            source, ("kind", "path", "framing", "event_envelope", "snapshot"), "source"
        )
        return {
            "kind": kind,
            "path": _require_abs_path(source.get("path"), "source.path"),
            "framing": parse_framing(source.get("framing"), "source.framing"),
            "event_envelope": parse_envelope(
                source.get("event_envelope"), "source.event_envelope"
            ),
            "snapshot": parse_snapshot(source.get("snapshot"), "source.snapshot"),
        }
    if kind == "json_stream":
        _reject_unknown(source, ("kind", "command", "path", "framing", "event_envelope"), "source")
        command = source.get("command")
        path = source.get("path")
        if (command is None) == (path is None):
            raise SpecError("spec_range", "source must set exactly one of command or path")
        return {
            "kind": kind,
            "command": None if command is None else _require_argv(command, "source.command"),
            "path": None if path is None else _require_abs_path(path, "source.path"),
            "framing": parse_framing(source.get("framing"), "source.framing"),
            "event_envelope": parse_envelope(
                source.get("event_envelope"), "source.event_envelope"
            ),
            "snapshot": None,
        }
    raise SpecError("spec_range", "source.kind must be unix_socket or json_stream")


def parse_match(raw) -> dict:
    match = _require_dict(raw, "match")
    _reject_unknown(
        match,
        ("subject_path", "subject", "status_path", "terminal_statuses", "event_id_path"),
        "match",
    )
    statuses = match.get("terminal_statuses")
    if not isinstance(statuses, list) or not statuses:
        raise SpecError("spec_type", "match.terminal_statuses must be a non-empty list")
    for status in statuses:
        _require_str(status, "match.terminal_statuses entry")
    event_id_raw = match.get("event_id_path")
    return {
        "subject_path": _require_path_list(match.get("subject_path"), "match.subject_path"),
        "subject": _require_str(match.get("subject"), "match.subject"),
        "status_path": _require_path_list(match.get("status_path"), "match.status_path"),
        "terminal_statuses": list(statuses),
        "event_id_path": (
            None if event_id_raw is None else _require_path_list(event_id_raw, "match.event_id_path")
        ),
    }


def parse_wake(raw) -> dict:
    if raw is None:
        return {"mode": "none"}
    wake = _require_dict(raw, "wake")
    mode = _require_str(wake.get("mode"), "wake.mode")
    if mode == "none":
        _reject_unknown(wake, ("mode",), "wake")
        return {"mode": "none"}
    if mode == "command":
        _reject_unknown(
            wake,
            ("mode", "owner", "argv", "ready_argv", "timeout_seconds", "append_receipt_path"),
            "wake",
        )
        ready_raw = wake.get("ready_argv")
        append = wake.get("append_receipt_path", False)
        if not isinstance(append, bool):
            raise SpecError("spec_type", "wake.append_receipt_path must be a boolean")
        return {
            "mode": "command",
            "owner": _require_str(wake.get("owner"), "wake.owner"),
            "argv": _require_argv(wake.get("argv"), "wake.argv"),
            "ready_argv": None if ready_raw is None else _require_argv(ready_raw, "wake.ready_argv"),
            "timeout_seconds": _require_number(
                wake.get("timeout_seconds", DEFAULT_WAKE_TIMEOUT_SECONDS),
                "wake.timeout_seconds",
                0.0,
                HARD_MAX_WAKE_TIMEOUT_SECONDS,
            ),
            "append_receipt_path": append,
        }
    raise SpecError("spec_range", "wake.mode must be none or command")


def parse_limits(raw) -> dict:
    if raw is None:
        return {
            "max_frame_bytes": DEFAULT_MAX_FRAME_BYTES,
            "max_record_bytes": DEFAULT_MAX_RECORD_BYTES,
        }
    limits = _require_dict(raw, "limits")
    _reject_unknown(limits, ("max_frame_bytes", "max_record_bytes"), "limits")
    return {
        "max_frame_bytes": int(
            _require_number(
                limits.get("max_frame_bytes", DEFAULT_MAX_FRAME_BYTES),
                "limits.max_frame_bytes",
                0.0,
                HARD_MAX_FRAME_BYTES,
            )
        ),
        "max_record_bytes": int(
            _require_number(
                limits.get("max_record_bytes", DEFAULT_MAX_RECORD_BYTES),
                "limits.max_record_bytes",
                0.0,
                HARD_MAX_RECORD_BYTES,
            )
        ),
    }


def parse_wait_id(raw) -> str:
    wait_id = _require_str(raw, "wait_id")
    if len(wait_id) > WAIT_ID_MAX_LEN:
        raise SpecError("spec_range", f"wait_id must be at most {WAIT_ID_MAX_LEN} characters")
    if set(wait_id) - WAIT_ID_ALLOWED:
        raise SpecError("spec_range", "wait_id may use letters, digits, dot, dash, underscore only")
    return wait_id


def parse_spec(raw) -> dict:
    spec = _require_dict(raw, "spec")
    _reject_unknown(
        spec,
        ("wait_id", "deadline_seconds", "receipt_path", "claim_dir", "source", "match", "wake", "limits"),
        "spec",
    )
    receipt_path = _require_abs_path(spec.get("receipt_path"), "receipt_path")
    claim_dir = spec.get("claim_dir")
    return {
        "wait_id": parse_wait_id(spec.get("wait_id")),
        "deadline_seconds": _require_number(
            spec.get("deadline_seconds"), "deadline_seconds", 0.0, HARD_MAX_DEADLINE_SECONDS
        ),
        "receipt_path": receipt_path,
        "claim_dir": (
            os.path.dirname(receipt_path)
            if claim_dir is None
            else _require_abs_path(claim_dir, "claim_dir")
        ),
        "source": parse_source(spec.get("source")),
        "match": parse_match(spec.get("match")),
        "wake": parse_wake(spec.get("wake")),
        "limits": parse_limits(spec.get("limits")),
    }


class Decoder:
    """Turn a byte stream into JSON records under a hard per-frame ceiling."""

    def __init__(self, framing: dict, max_frame_bytes: int) -> None:
        self.framing = framing
        self.max_frame_bytes = max_frame_bytes
        self.buffer = b""

    @property
    def pending_bytes(self) -> int:
        return len(self.buffer)

    def feed(self, chunk: bytes) -> list[dict]:
        self.buffer += chunk
        if self.framing["kind"] == "lines":
            return self._feed_lines()
        return self._feed_length_prefix()

    def finish(self) -> list[dict]:
        """Decode what end-of-stream left behind, if it is a whole record.

        A `lines` source is free to end its last record with EOF instead of a
        newline, so a complete trailing object is decoded here rather than
        reported as a truncated frame. Bytes that are not complete JSON stay
        in the buffer, where the caller still reports them as truncated; a
        length-prefixed frame that is short of its declared length is always
        truncated, so nothing is salvaged from it.
        """
        if self.framing["kind"] != "lines":
            return []
        if not self.buffer.strip():
            self.buffer = b""
            return []
        if self._load_json(self.buffer) is MISSING:
            return []
        payload, self.buffer = self.buffer, b""
        return [self._decode_payload(payload)]

    def _load_json(self, payload: bytes):
        """The JSON value these bytes hold, or MISSING if they are not JSON."""
        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return MISSING

    def _decode_payload(self, payload: bytes) -> dict:
        record = self._load_json(payload)
        if record is MISSING:
            raise SourceError(
                "invalid_json", f"frame of {len(payload)} bytes is not valid JSON"
            )
        if not isinstance(record, dict):
            raise SourceError(
                "invalid_record", f"frame of {len(payload)} bytes is not a JSON object"
            )
        return record

    def _feed_lines(self) -> list[dict]:
        records = []
        while True:
            index = self.buffer.find(b"\n")
            if index < 0:
                if len(self.buffer) > self.max_frame_bytes:
                    raise SourceError(
                        "frame_too_large",
                        f"unterminated record exceeded {self.max_frame_bytes} bytes",
                    )
                return records
            line, self.buffer = self.buffer[:index], self.buffer[index + 1 :]
            if len(line) > self.max_frame_bytes:
                raise SourceError(
                    "frame_too_large",
                    f"record of {len(line)} bytes exceeds {self.max_frame_bytes} bytes",
                )
            if line.strip():
                records.append(self._decode_payload(line))

    def _feed_length_prefix(self) -> list[dict]:
        width = self.framing["prefix_bytes"]
        order = self.framing["byte_order"]
        records = []
        while len(self.buffer) >= width:
            length = int.from_bytes(self.buffer[:width], order)
            if length > self.max_frame_bytes:
                raise SourceError(
                    "frame_too_large",
                    f"frame header declares {length} bytes, over the {self.max_frame_bytes} byte limit",
                )
            if len(self.buffer) < width + length:
                return records
            payload = self.buffer[width : width + length]
            self.buffer = self.buffer[width + length :]
            records.append(self._decode_payload(payload))
        return records


class SocketChannel:
    """A connected Unix socket. Writable only when a snapshot is configured."""

    def __init__(self, path: str) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self.sock.connect(path)
        except OSError as exc:
            self.sock.close()
            raise SourceError(
                "connect_failed", f"cannot connect to the configured socket ({errno.errorcode.get(exc.errno, 'error')})"
            ) from exc

    def recv(self, timeout: float) -> bytes:
        self.sock.settimeout(timeout)
        try:
            return self.sock.recv(READ_CHUNK_BYTES)
        except socket.timeout:
            raise Timeout() from None
        except OSError as exc:
            raise SourceError(
                "read_failed", f"socket read failed ({errno.errorcode.get(exc.errno, 'error')})"
            ) from exc

    def send(self, payload: bytes) -> None:
        try:
            self.sock.sendall(payload)
        except OSError as exc:
            raise SourceError(
                "write_failed", f"snapshot request failed ({errno.errorcode.get(exc.errno, 'error')})"
            ) from exc

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError as exc:
            print(f"event-wait: closing source socket failed: {exc}", file=sys.stderr)


class StreamChannel:
    """A read-only byte stream: our own subprocess's output, or a fifo/file."""

    def __init__(self, command: list[str] | None, path: str | None) -> None:
        self.process = None
        self.fd = -1
        if command is not None:
            try:
                self.process = subprocess.Popen(command, stdout=subprocess.PIPE)
            except OSError as exc:
                raise SourceError(
                    "spawn_failed", f"cannot start the configured source command ({exc.strerror})"
                ) from exc
            self.fd = self.process.stdout.fileno()
            return
        try:
            self.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError as exc:
            raise SourceError(
                "open_failed",
                f"cannot open the configured source path ({errno.errorcode.get(exc.errno, 'error')})",
            ) from exc

    def recv(self, timeout: float) -> bytes:
        ready, _, _ = select.select([self.fd], [], [], timeout)
        if not ready:
            raise Timeout()
        try:
            return os.read(self.fd, READ_CHUNK_BYTES)
        except BlockingIOError:
            return WOULD_BLOCK
        except OSError as exc:
            raise SourceError(
                "read_failed", f"stream read failed ({errno.errorcode.get(exc.errno, 'error')})"
            ) from exc

    def send(self, payload: bytes) -> None:
        raise SourceError("read_only_source", "this source accepts no requests")

    def close(self) -> None:
        if self.process is not None:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired) as exc:
                print(f"event-wait: stopping source command failed: {exc}", file=sys.stderr)
            finally:
                if self.process.stdout is not None:
                    self.process.stdout.close()
            return
        try:
            os.close(self.fd)
        except OSError as exc:
            print(f"event-wait: closing source stream failed: {exc}", file=sys.stderr)


class Claim:
    """Exclusive ownership of one wait id and one private receipt path.

    Both are taken with O_CREAT|O_EXCL, so two waits racing for the same id or
    the same receipt path can never both win. The receipt descriptor stays open
    for the life of the wait and receives the single terminal receipt.
    """

    def __init__(self, wait_id: str, receipt_path: str, claim_dir: str) -> None:
        self.wait_id = wait_id
        self.receipt_path = receipt_path
        self.claim_path = os.path.join(claim_dir, f"{wait_id}.claim")
        self.receipt_fd = -1
        self.claim_fd = -1
        self.written = False
        self._check_private(os.path.dirname(receipt_path), "receipt_path")
        self._check_private(claim_dir, "claim_dir")
        self.claim_fd = self._exclusive(self.claim_path, "wait_id_in_use")
        try:
            self.receipt_fd = self._exclusive(receipt_path, "receipt_path_in_use")
        except ClaimError:
            self._release_claim()
            raise
        os.write(self.claim_fd, f"{os.getpid()} {wait_id}\n".encode("utf-8"))

    @staticmethod
    def _check_private(directory: str, where: str) -> None:
        try:
            mode = os.stat(directory).st_mode
        except OSError as exc:
            raise ClaimError(
                "claim_dir_unusable",
                f"{where} directory is unreadable ({errno.errorcode.get(exc.errno, 'error')})",
            ) from exc
        if mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise ClaimError(
                "receipt_dir_not_private",
                f"{where} directory is group- or world-writable",
            )

    @staticmethod
    def _exclusive(path: str, code: str) -> int:
        try:
            return os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        except FileExistsError:
            raise ClaimError(code, f"{os.path.basename(path)} is already owned") from None
        except OSError as exc:
            raise ClaimError(
                "claim_failed",
                f"cannot claim {os.path.basename(path)} ({errno.errorcode.get(exc.errno, 'error')})",
            ) from exc

    def write_receipt(self, receipt: dict) -> None:
        if self.written:
            return
        self.written = True
        payload = (json.dumps(receipt, sort_keys=True) + "\n").encode("utf-8")
        try:
            os.lseek(self.receipt_fd, 0, os.SEEK_SET)
            os.ftruncate(self.receipt_fd, 0)
            os.write(self.receipt_fd, payload)
            os.fsync(self.receipt_fd)
        except OSError as exc:
            print(
                f"event-wait: writing the receipt for {self.wait_id} failed: {exc}",
                file=sys.stderr,
            )
            raise

    def _release_claim(self) -> None:
        if self.claim_fd >= 0:
            try:
                os.close(self.claim_fd)
            except OSError as exc:
                print(f"event-wait: closing claim file failed: {exc}", file=sys.stderr)
            self.claim_fd = -1
        try:
            os.unlink(self.claim_path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            print(f"event-wait: removing claim file failed: {exc}", file=sys.stderr)

    def release(self) -> None:
        """Drop only this wait's own resources. The receipt file is kept."""
        self._release_claim()
        if self.receipt_fd >= 0:
            try:
                os.close(self.receipt_fd)
            except OSError as exc:
                print(f"event-wait: closing receipt file failed: {exc}", file=sys.stderr)
            self.receipt_fd = -1


class Wait:
    """One blocking wait: attach, acknowledge, snapshot once, then consume."""

    def __init__(self, spec: dict, claim: Claim, out=sys.stdout) -> None:
        self.spec = spec
        self.claim = claim
        self.out = out
        self.channel = None
        self.decoder = Decoder(spec["source"]["framing"], spec["limits"]["max_frame_bytes"])
        self.started = time.monotonic()
        self.deadline = self.started + spec["deadline_seconds"]
        self.requests_sent = 0
        self.duplicates_skipped = 0
        self.seen_event_ids: dict[str, bool] = {}
        self.events_during_snapshot = 0
        self.snapshot_open = False
        self.snapshot_request_id = None

    def remaining(self) -> float:
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise Timeout()
        return left

    def emit(self, record: dict) -> None:
        self.out.write(json.dumps(record, sort_keys=True) + "\n")
        self.out.flush()

    def callback_readiness(self) -> tuple[bool, str]:
        wake = self.spec["wake"]
        if wake["mode"] == "none":
            return False, "session_wake_unsupported"
        if wake["ready_argv"] is None:
            return False, "unproven"
        try:
            completed = subprocess.run(
                wake["ready_argv"],
                timeout=wake["timeout_seconds"],
                stdout=subprocess.DEVNULL,
                env=self.wake_env(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"event-wait: wake readiness probe failed to run: {exc}", file=sys.stderr)
            return False, "not_ready"
        if completed.returncode != 0:
            print(
                f"event-wait: wake readiness probe exited {completed.returncode}",
                file=sys.stderr,
            )
            return False, "not_ready"
        return True, "ready"

    def wake_env(self, status: str | None = None) -> dict:
        env = dict(os.environ)
        env["EVENT_WAIT_ID"] = self.spec["wait_id"]
        env["EVENT_WAIT_RECEIPT_PATH"] = self.spec["receipt_path"]
        env["EVENT_WAIT_SUBJECT"] = self.spec["match"]["subject"]
        env["EVENT_WAIT_STATUS"] = status or ""
        if self.spec["wake"]["mode"] == "command":
            env["EVENT_WAIT_OWNER"] = self.spec["wake"]["owner"]
        return env

    def attach(self) -> None:
        source = self.spec["source"]
        if source["kind"] == "unix_socket":
            self.channel = SocketChannel(source["path"])
        else:
            self.channel = StreamChannel(source["command"], source["path"])

    def send_snapshot(self) -> None:
        """Send at most one initial request. Nothing else ever writes."""
        snapshot = self.spec["source"]["snapshot"]
        if snapshot is None:
            return
        if self.requests_sent:
            raise SourceError("snapshot_repeat", "a snapshot request was already sent")
        request = dict(snapshot["request"])
        if snapshot["request_id_field"] is not None:
            self.snapshot_request_id = snapshot["request_id_value"] or f"ew-{os.getpid()}"
            request[snapshot["request_id_field"]] = self.snapshot_request_id
        payload = json.dumps(request).encode("utf-8")
        framing = self.spec["source"]["framing"]
        if framing["kind"] == "length_prefix":
            frame = len(payload).to_bytes(framing["prefix_bytes"], framing["byte_order"]) + payload
        else:
            frame = payload + b"\n"
        self.channel.send(frame)
        self.requests_sent += 1
        self.snapshot_open = True

    def is_duplicate(self, body: dict) -> bool:
        """Has this exact event already been seen? Only ever asked of our own subject.

        Event identity is only unique within a subject: a shared channel can
        carry another subject's event under an identifier ours will reuse
        later. Recording foreign identifiers here would let a neighbour's
        event mark this wait's own completion as already seen, so the wait
        would sit out a job that had already finished.
        """
        path = self.spec["match"]["event_id_path"]
        if path is None:
            return False
        event_id = dig(body, path)
        if event_id is MISSING or not isinstance(event_id, (str, int)):
            return False
        key = str(event_id)
        if key in self.seen_event_ids:
            self.duplicates_skipped += 1
            return True
        if len(self.seen_event_ids) >= MAX_SEEN_EVENT_IDS:
            self.seen_event_ids.pop(next(iter(self.seen_event_ids)))
        self.seen_event_ids[key] = True
        return False

    def is_subject(self, body) -> bool:
        """Does this body report on the exact subject this wait owns?"""
        if not isinstance(body, dict):
            return False
        match = self.spec["match"]
        subject = dig(body, match["subject_path"])
        return subject is not MISSING and subject == match["subject"]

    def terminal_status(self, body) -> str | None:
        """The terminal status this body reports for our subject, if any."""
        if not self.is_subject(body):
            return None
        match = self.spec["match"]
        status = dig(body, match["status_path"])
        if status is MISSING or not isinstance(status, str):
            return None
        if status not in match["terminal_statuses"]:
            return None
        return status

    def classify(self, record: dict) -> tuple[str, dict | None]:
        """Label one decoded record: our snapshot answer, an event, or noise."""
        source = self.spec["source"]
        snapshot = source["snapshot"]
        if snapshot is not None and self.snapshot_open and self._snapshot_addressed(record, snapshot):
            if snapshot["error_match_fields"] and envelope_matches(
                record, snapshot["error_match_fields"]
            ):
                return "snapshot_error", None
            if envelope_matches(record, snapshot["response_match_fields"]):
                return "snapshot_response", dig(record, snapshot["body_path"])
        envelope = source["event_envelope"]
        if envelope_matches(record, envelope["match_fields"]):
            body = dig(record, envelope["body_path"])
            if body is not MISSING:
                return "event", body
        return "ignored", None

    def _snapshot_addressed(self, record: dict, snapshot: dict) -> bool:
        field = snapshot["request_id_field"]
        if field is None:
            return True
        return record.get(field) == self.snapshot_request_id

    def consume(self) -> dict:
        """Block until a terminal event matches, or a terminal condition hits."""
        while True:
            chunk = self.channel.recv(self.remaining())
            if chunk is WOULD_BLOCK:
                continue
            if not chunk:
                for record in self.decoder.finish():
                    outcome = self.handle(record)
                    if outcome is not None:
                        return outcome
                if self.decoder.pending_bytes:
                    raise SourceError(
                        "truncated_frame",
                        f"source closed with {self.decoder.pending_bytes} unread bytes",
                    )
                raise SourceError("source_closed", "source closed before a matching event")
            for record in self.decoder.feed(chunk):
                outcome = self.handle(record)
                if outcome is not None:
                    return outcome
            self.remaining()

    def handle(self, record: dict) -> dict | None:
        """Reconcile one record against the wait, returning a match or None.

        A live event is matched the moment it arrives, including while the one
        snapshot request is still in flight, so a completion that lands inside
        the snapshot window is never parked behind a reply that may never come.
        The snapshot only ever reports state from before the request, so it can
        never overtake a live event; event identity keeps the two from counting
        the same completion twice.
        """
        kind, body = self.classify(record)
        if kind == "snapshot_error":
            self.snapshot_open = False
            raise SourceError(
                "snapshot_rejected", "the source rejected the initial snapshot request"
            )
        if kind == "snapshot_response":
            self.snapshot_open = False
            if not self.is_subject(body):
                return None
            if self.is_duplicate(body):
                return None
            status = self.terminal_status(body)
            if status is None:
                return None
            return {"matched_via": "snapshot", "status": status, "body": body}
        if kind != "event":
            return None
        if self.snapshot_open:
            self.events_during_snapshot += 1
        if not self.is_subject(body):
            return None
        if self.is_duplicate(body):
            return None
        status = self.terminal_status(body)
        if status is None:
            return None
        return {"matched_via": "stream", "status": status, "body": body}

    def excerpt(self, body) -> tuple[str, bool]:
        limit = self.spec["limits"]["max_record_bytes"]
        try:
            text = json.dumps(body, sort_keys=True)
        except (TypeError, ValueError) as exc:
            print(f"event-wait: matched body is not serialisable: {exc}", file=sys.stderr)
            return "", True
        raw = text.encode("utf-8")
        if len(raw) <= limit:
            return text, False
        return raw[:limit].decode("utf-8", "ignore"), True

    def deliver_wake(self, status: str) -> tuple[bool, str]:
        wake = self.spec["wake"]
        if wake["mode"] == "none":
            return False, "session_wake_unsupported"
        argv = list(wake["argv"])
        if wake["append_receipt_path"]:
            argv.append(self.spec["receipt_path"])
        try:
            completed = subprocess.run(
                argv, timeout=wake["timeout_seconds"], env=self.wake_env(status)
            )
        except subprocess.TimeoutExpired:
            print(
                f"event-wait: wake command timed out after {wake['timeout_seconds']}s",
                file=sys.stderr,
            )
            return False, "failed"
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"event-wait: wake command failed to run: {exc}", file=sys.stderr)
            return False, "failed"
        if completed.returncode != 0:
            print(
                f"event-wait: wake command exited {completed.returncode}; this is the wake's own "
                "exit code and says nothing about the watched job's outcome",
                file=sys.stderr,
            )
            return False, "failed"
        return True, "delivered"


def base_receipt(spec: dict) -> dict:
    return {
        "record": "receipt",
        "schema": SCHEMA_RECEIPT,
        "wait_id": spec["wait_id"],
        "subject": spec["match"]["subject"],
        "outcome": "unknown",
        "event_received": False,
        "wake_delivered": False,
        "wake_status": "not_armed",
        "matched_via": None,
        "status": None,
        "event_excerpt": "",
        "event_truncated": False,
        "error_code": None,
        "error_detail": None,
        "source_requests_sent": 0,
        "duplicate_events_skipped": 0,
        "events_during_snapshot": 0,
        "elapsed_seconds": 0.0,
        "exit_code": EXIT_MATCHED,
    }


def install_signal_handlers() -> None:
    def handler(signum, frame):
        raise Cancelled()

    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)


def run(spec: dict, out=sys.stdout) -> int:
    claim = Claim(spec["wait_id"], spec["receipt_path"], spec["claim_dir"])
    wait = Wait(spec, claim, out)
    receipt = base_receipt(spec)
    try:
        callback_ready, callback_status = wait.callback_readiness()
        try:
            wait.attach()
        except SourceError as exc:
            wait.emit(
                {
                    "record": "armed",
                    "schema": SCHEMA_ARMED,
                    "wait_id": spec["wait_id"],
                    "source_ready": False,
                    "callback_ready": callback_ready,
                    "callback_status": callback_status,
                    "error_code": exc.code,
                }
            )
            raise
        wait.emit(
            {
                "record": "armed",
                "schema": SCHEMA_ARMED,
                "wait_id": spec["wait_id"],
                "subject": spec["match"]["subject"],
                "source_ready": True,
                "callback_ready": callback_ready,
                "callback_status": callback_status,
                "error_code": None,
            }
        )
        wait.send_snapshot()
        matched = wait.consume()
        receipt["event_received"] = True
        receipt["matched_via"] = matched["matched_via"]
        receipt["status"] = matched["status"]
        receipt["event_excerpt"], receipt["event_truncated"] = wait.excerpt(matched["body"])
        delivered, wake_status = wait.deliver_wake(matched["status"])
        receipt["wake_delivered"] = delivered
        receipt["wake_status"] = wake_status
        receipt["outcome"] = "matched"
        receipt["exit_code"] = EXIT_CALLBACK_FAILED if wake_status == "failed" else EXIT_MATCHED
    except Timeout:
        receipt["outcome"] = "timeout"
        receipt["error_code"] = "deadline_exceeded"
        receipt["error_detail"] = f"no matching event within {spec['deadline_seconds']}s"
        receipt["exit_code"] = EXIT_TIMEOUT
    except SourceError as exc:
        receipt["outcome"] = "source_error"
        receipt["error_code"] = exc.code
        receipt["error_detail"] = exc.detail
        receipt["exit_code"] = EXIT_SOURCE_ERROR
    except Cancelled:
        receipt["outcome"] = "cancelled"
        receipt["error_code"] = "cancelled"
        receipt["error_detail"] = "this wait received a termination signal"
        receipt["exit_code"] = EXIT_CANCELLED
    finally:
        if wait.channel is not None:
            wait.channel.close()
        receipt["source_requests_sent"] = wait.requests_sent
        receipt["duplicate_events_skipped"] = wait.duplicates_skipped
        receipt["events_during_snapshot"] = wait.events_during_snapshot
        receipt["elapsed_seconds"] = round(time.monotonic() - wait.started, 3)
        claim.write_receipt(receipt)
        claim.release()
    wait.emit(receipt)
    return receipt["exit_code"]


def load_spec_text(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError as exc:
        raise SpecError("spec_unreadable", f"cannot read the spec file ({exc.strerror})") from exc


def fail(code: str, detail: str, exit_code: int, out=sys.stdout) -> int:
    out.write(
        json.dumps(
            {
                "record": "receipt",
                "schema": SCHEMA_RECEIPT,
                "outcome": "spec_invalid" if exit_code == EXIT_SPEC_INVALID else "claim_conflict",
                "event_received": False,
                "wake_delivered": False,
                "wake_status": "not_armed",
                "error_code": code,
                "error_detail": detail,
                "exit_code": exit_code,
            },
            sort_keys=True,
        )
        + "\n"
    )
    out.flush()
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Block on one event from a push source.")
    parser.add_argument("--spec", required=True, help="path to the JSON wait spec, or - for stdin")
    args = parser.parse_args(argv)
    install_signal_handlers()
    try:
        raw = json.loads(load_spec_text(args.spec))
    except ValueError:
        return fail("spec_invalid_json", "the spec is not valid JSON", EXIT_SPEC_INVALID)
    except SpecError as exc:
        return fail(exc.code, exc.detail, EXIT_SPEC_INVALID)
    try:
        spec = parse_spec(raw)
    except SpecError as exc:
        return fail(exc.code, exc.detail, EXIT_SPEC_INVALID)
    try:
        return run(spec)
    except ClaimError as exc:
        return fail(exc.code, exc.detail, EXIT_CLAIM_CONFLICT)


if __name__ == "__main__":
    sys.exit(main())
