#!/usr/bin/env python3
"""Bounded, blocking event consumer. No status polling, shell, or producer process."""
import argparse
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import select
import signal
import socket
import stat
import struct
import sys
import time

LIMIT = 65536
MAX_IDS = 4096
LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
MISSING = object()


class Failure(Exception):
    """Only fixed codes, never producer data, reach diagnostics."""


def require(condition, code="invalid_spec"):
    if not condition:
        raise Failure(code)


def decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "malformed_json")
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _: require(False, "malformed_json"))
        require(isinstance(value, dict), "malformed_json")
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise Failure("malformed_json") from None


def label(value):
    require(isinstance(value, str) and LABEL.fullmatch(value))


def fields(value, required, optional=()):
    require(isinstance(value, dict) and set(required) <= value.keys()
            and value.keys() <= set(required) | set(optional))


def path(value):
    require(isinstance(value, list) and 1 <= len(value) <= 12)
    for part in value:
        require((isinstance(part, str) and 0 < len(part) <= 128)
                or (type(part) is int and 0 <= part <= 4096))


def predicates(value):
    require(isinstance(value, list) and 1 <= len(value) <= 16)
    for item in value:
        fields(item, ("path", "equals"))
        path(item["path"])
        require(isinstance(item["equals"], (str, int, bool))
                and len(str(item["equals"])) <= 256)


def mapping(value, event=True):
    fields(value, ("subject", "identity_paths", "status_path", "terminal"),
           ("channel", "filters"))
    predicates(value["subject"])
    if event:
        require("channel" in value)
    if "channel" in value:
        predicates([value["channel"]])
    if "filters" in value:
        predicates(value["filters"])
    require(isinstance(value["identity_paths"], list)
            and 1 <= len(value["identity_paths"]) <= 8)
    for item in value["identity_paths"]:
        path(item)
    path(value["status_path"])
    require(isinstance(value["terminal"], dict) and 1 <= len(value["terminal"]) <= 16)
    for key, outcome in value["terminal"].items():
        require(0 < len(key) <= 128 and outcome in ("success", "failure", "cancelled"))


def absolute(value):
    require(isinstance(value, str) and os.path.isabs(value) and "\0" not in value)
    require(str(Path(value)) == value)


def validate(spec):
    fields(spec, ("wait_id", "registry", "receipt", "deadline", "source", "wake"))
    label(spec["wait_id"])
    absolute(spec["registry"])
    absolute(spec["receipt"])
    require(spec["receipt"] == str(Path(spec["registry"]) / spec["wait_id"] / "terminal.json"))
    require(type(spec["deadline"]) in (int, float) and math.isfinite(spec["deadline"]))
    require(spec["deadline"] - time.time() <= 604800)
    src = spec["source"]
    fields(src, ("identity", "transport", "read_only", "event"),
           ("path", "subscribe", "snapshot"))
    label(src["identity"])
    require(src["read_only"] is True)
    require(src["transport"] in ("unix", "stdin"))
    mapping(src["event"])
    if src["transport"] == "unix":
        absolute(src.get("path"))
        require(len(os.fsencode(src["path"])) < 104)
    else:
        require(not any(k in src for k in ("path", "subscribe", "snapshot")))
    for name in ("subscribe", "snapshot"):
        if name not in src:
            continue
        req = src[name]
        fields(req, ("request", "response"),
               ("error", "record_path", "mapping") if name == "snapshot" else ("error",))
        require(isinstance(req["request"], dict))
        predicates(req["response"])
        if "error" in req:
            predicates(req["error"])
        if name == "snapshot":
            path(req.get("record_path"))
            mapping(req.get("mapping"), event=False)
    wake = spec["wake"]
    fields(wake, ("mode", "owner"), ("socket",))
    label(wake["owner"])
    require(wake["mode"] in ("unsupported", "native", "acknowledged"))
    if wake["mode"] != "unsupported":
        absolute(wake.get("socket"))
        require(len(os.fsencode(wake["socket"])) < 104)
        require(wake["socket"] != src.get("path"))
    else:
        require("socket" not in wake)
    return spec


def lookup(record, parts):
    for part in parts:
        if isinstance(record, dict) and isinstance(part, str):
            record = record.get(part, MISSING)
        elif isinstance(record, list) and type(part) is int and part < len(record):
            record = record[part]
        else:
            return MISSING
    return record


def matches(record, checks):
    return all(type(v := lookup(record, check["path"])) is type(check["equals"])
               and v == check["equals"] for check in checks)


class Clock:
    def __init__(self, absolute_deadline):
        self.end = time.monotonic() + max(0, absolute_deadline - time.time())

    def remaining(self):
        left = self.end - time.monotonic()
        require(left > 0, "timeout")
        return left

    def ready(self, fd, write=False):
        left = self.remaining()
        readable, writable, _ = select.select([] if write else [fd], [fd] if write else [], [], left)
        require(bool(readable or writable), "timeout")


class Stream:
    def __init__(self, fd, clock, framed=True):
        self.fd, self.clock, self.framed = fd, clock, framed
        self.buffer = bytearray()

    def read(self):
        while True:
            self.clock.remaining()  # Also enforce deadlines with continuously buffered traffic.
            if self.framed and len(self.buffer) >= 4:
                size = struct.unpack("!I", self.buffer[:4])[0]
                require(0 < size <= LIMIT, "oversize_frame")
                if len(self.buffer) >= size + 4:
                    raw = bytes(self.buffer[4:size + 4])
                    del self.buffer[:size + 4]
                    return decode(raw)
            elif not self.framed:
                newline = self.buffer.find(b"\n")
                if newline >= 0:
                    require(newline <= LIMIT, "oversize_record")
                    raw = bytes(self.buffer[:newline])
                    del self.buffer[:newline + 1]
                    return decode(raw)
                require(len(self.buffer) <= LIMIT, "oversize_record")
            self.clock.ready(self.fd)
            chunk = os.read(self.fd, min(4096, LIMIT + 5 - len(self.buffer)))
            require(bool(chunk), "truncated_stream" if self.buffer else "source_eof")
            self.buffer.extend(chunk)

    def send(self, record):
        raw = json.dumps(record, separators=(",", ":"), allow_nan=False).encode()
        require(len(raw) <= LIMIT, "oversize_output")
        pending = memoryview(struct.pack("!I", len(raw)) + raw)
        while pending:
            self.clock.ready(self.fd, write=True)
            size = os.write(self.fd, pending)
            require(size > 0, "source_disconnect")
            pending = pending[size:]


def connect(endpoint, clock):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.setblocking(False)
        result = sock.connect_ex(endpoint)
        if result in (errno.EINPROGRESS, errno.EAGAIN, errno.EWOULDBLOCK):
            clock.ready(sock.fileno(), write=True)
            result = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        require(result == 0, "connect_failed")
        return sock
    except BaseException:
        sock.close()
        raise


class Receipts:
    """Atomic namespace claim; directory remains a tombstone against ID reuse."""
    def __init__(self, spec):
        self.fd = None
        root = os.open(spec["registry"], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(root)
            require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
                    "registry_not_private")
            try:
                os.mkdir(spec["wait_id"], 0o700, dir_fd=root)
            except FileExistsError:
                raise Failure("ownership_conflict") from None
            self.fd = os.open(spec["wait_id"], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
        finally:
            os.close(root)

    def write(self, name, record):
        raw = (json.dumps(record, separators=(",", ":")) + "\n").encode()
        require(len(raw) <= 4096, "oversize_output")
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
        with os.fdopen(fd, "wb") as out:
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())

    def close(self):
        os.close(self.fd)


def announce(record):
    raw = (json.dumps(record, separators=(",", ":")) + "\n").encode()
    require(len(raw) <= 4096, "oversize_output")
    try:
        require(os.write(sys.stdout.fileno(), raw) == len(raw), "output_failed")
    except (OSError, ValueError):
        raise Failure("output_failed") from None


class Consumer:
    def __init__(self, spec, receipts):
        self.spec, self.receipts = spec, receipts
        self.clock = Clock(spec["deadline"])
        self.seen = set()
        self.terminal = None
        self.snapshots = 0
        self.sockets = []
        self.state = {"wait_id": spec["wait_id"], "source": spec["source"]["identity"],
                      "owner": spec["wake"]["owner"], "nonce": secrets.token_hex(16),
                      "source_ready": False, "callback_ready": False,
                      "event_received": False, "wake_delivered": False,
                      "target_outcome": None}

    def socket_stream(self, endpoint):
        sock = connect(endpoint, self.clock)
        self.sockets.append(sock)
        return Stream(sock.fileno(), self.clock)

    def observe(self, record, config, origin):
        checks = config["subject"] + config.get("filters", [])
        if "channel" in config:
            checks = checks + [config["channel"]]
        if not matches(record, checks):
            return
        identity = [lookup(record, p) for p in config["identity_paths"]]
        require(all(type(v) in (str, int) and len(str(v)) <= 256 for v in identity), "invalid_event_identity")
        digest = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
        if digest in self.seen:
            return
        require(len(self.seen) < MAX_IDS, "identity_limit")
        self.seen.add(digest)
        status = lookup(record, config["status_path"])
        require(isinstance(status, str), "invalid_event_status")
        outcome = config["terminal"].get(status)
        # Terminal transitions must be irreversible within the exact selected attempt.
        # A streamed terminal observed during snapshot wins over a stale snapshot.
        if outcome and self.terminal is None:
            self.terminal = {"event_digest": digest, "target_outcome": outcome, "origin": origin}

    def request(self, stream, config, snapshot=False):
        stream.send(config["request"])
        if snapshot:
            self.snapshots += 1
        while True:
            record = stream.read()
            if "error" in config and matches(record, config["error"]):
                raise Failure("source_request_failed")
            if matches(record, config["response"]):
                if snapshot:
                    item = lookup(record, config["record_path"])
                    require(isinstance(item, dict), "invalid_snapshot")
                    self.observe(item, config["mapping"], "snapshot")
                return
            self.observe(record, self.spec["source"]["event"], "stream")

    def callback_message(self, kind):
        return {k: self.state[k] for k in ("wait_id", "owner", "nonce")} | {"type": kind}

    def callback_ack(self, stream, kind):
        answer = stream.read()
        expected = self.callback_message(kind)
        require(answer == expected, "callback_invalid_ack")

    def run(self):
        wake = self.spec["wake"]
        try:
            src = self.spec["source"]
            self.clock.remaining()
            stream = (self.socket_stream(src["path"]) if src["transport"] == "unix"
                      else Stream(sys.stdin.fileno(), self.clock, framed=False))
            if "subscribe" in src:
                self.request(stream, src["subscribe"])
            self.state["source_ready"] = True
            ready = self.callback_message("source_ready")
            ready["scope"] = "subscription_ack" if "subscribe" in src else "transport_only"
            self.receipts.write("source-ready.json", ready)
            announce(ready)
            callback = None
            if wake["mode"] != "unsupported":
                try:
                    callback = self.socket_stream(wake["socket"])
                    callback.send(self.callback_message("register"))
                    self.callback_ack(callback, "callback_ready")
                except Failure as exc:
                    if str(exc) in ("cancelled", "timeout"):
                        raise
                    raise Failure("callback_failed") from None
                except OSError:
                    raise Failure("callback_failed") from None
                self.state["callback_ready"] = True
                ready = self.callback_message("callback_ready")
                self.receipts.write("callback-ready.json", ready)
                announce(ready)
            if "snapshot" in src:
                self.request(stream, src["snapshot"], snapshot=True)
            while self.terminal is None:
                self.observe(stream.read(), src["event"], "stream")
            self.state.update(self.terminal)
            self.state["event_received"] = True
            self.receipts.write("event.json", self.state)
            if callback is None:
                raise Failure("session_wake_unsupported")
            try:
                callback.send(self.callback_message("event_received") | self.terminal)
                if wake["mode"] == "acknowledged":
                    self.callback_ack(callback, "wake_delivered")
                    self.state["wake_delivered"] = True
            except Failure as exc:
                if str(exc) in ("cancelled", "timeout"):
                    raise
                raise Failure("callback_failed") from None
            except OSError:
                raise Failure("callback_failed") from None
            return "wake_delivered" if self.state["wake_delivered"] else "wake_pending", 0
        except Failure as exc:
            return str(exc), 1
        except OSError:
            return "io_error", 1
        finally:
            for sock in self.sockets:
                sock.close()

    def finish(self, result, code):
        self.state.update(result=result, exit_code=code, snapshot_requests=self.snapshots)
        self.receipts.write("terminal.json", self.state)
        announce(self.state)


def acknowledge(receipt, owner, nonce):
    """Called by the resumed owning harness, never automatically by the listener."""
    absolute(receipt)
    label(owner)
    with open(receipt, "rb") as handle:
        raw = handle.read(LIMIT + 1)
    require(len(raw) <= LIMIT, "oversize_record")
    record = decode(raw)
    require(record.get("result") == "wake_pending" and record.get("owner") == owner
            and record.get("nonce") == nonce, "acknowledgment_mismatch")
    directory = os.open(str(Path(receipt).parent), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(directory)
        require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700, "registry_not_private")
        fd = os.open("wake-delivered.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        with os.fdopen(fd, "w") as handle:
            json.dump({"wait_id": record["wait_id"], "owner": owner, "nonce": nonce,
                       "wake_delivered": True, "attestation": "resumed_owner"}, handle)
    finally:
        os.close(directory)
    announce({"wait_id": record["wait_id"], "wake_delivered": True})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    wait = sub.add_parser("wait")
    wait.add_argument("--spec", required=True)
    ack = sub.add_parser("ack-wake")
    ack.add_argument("--receipt", required=True)
    ack.add_argument("--owner", required=True)
    ack.add_argument("--nonce", required=True)
    args = parser.parse_args()
    receipts = None
    try:
        os.set_blocking(sys.stdout.fileno(), False)
        if args.command == "ack-wake":
            acknowledge(args.receipt, args.owner, args.nonce)
            return 0
        with open(args.spec, "rb") as handle:
            raw = handle.read(LIMIT + 1)
        require(len(raw) <= LIMIT, "oversize_spec")
        spec = validate(decode(raw))
        receipts = Receipts(spec)
        def cancel(_signum, _frame):
            raise Failure("cancelled")
        signal.signal(signal.SIGTERM, cancel)
        signal.signal(signal.SIGINT, cancel)
        consumer = Consumer(spec, receipts)
        result, code = consumer.run()
        # Finish once; a repeated cancellation cannot interrupt receipt writing.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        consumer.finish(result, code)
        return code
    except (Failure, OSError, ValueError) as exc:
        code = str(exc) if isinstance(exc, Failure) else "local_io_error"
        print(json.dumps({"error": code}), file=sys.stderr)
        return 2
    finally:
        if receipts is not None:
            receipts.close()


if __name__ == "__main__":
    sys.exit(main())
