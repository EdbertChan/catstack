#!/usr/bin/env python3
"""Capture a CI job log to disk once, then answer bounded questions about it.

A failed CI job log is the classic context-window hazard: it is large, it is
read more than once, and re-reading it means downloading it again. This helper
splits the two jobs that a plain `gh run view --log` fuses together.

    capture   Stream the log to a private artifact directory. Full bytes are
              preserved, hashed, and described by a manifest. The response
              carries no log bytes at all.
    snippet   Answer one bounded question about an already-captured artifact,
              with no network call. The response is capped at HARD_LIMIT UTF-8
              bytes including every field, not just the excerpt text.

Invariants this file is responsible for:

  * Original bytes, provenance and producer exit status survive untouched on
    disk. Selection happens on the way out, never on the way in.
  * A response never exceeds the byte cap, whatever the log contains: one
    300KB line, dense multibyte text, or thousands of failure markers.
  * Selection never turns a failure into a success. The producer exit status,
    the job conclusion and the artifact completeness ride along in every
    response, and "no marker matched" is reported as `no_match`, never as a
    clean result.
  * A check that could not run is not a pass. A line longer than the scan
    window is counted in `matches.lines_unscanned`; a job whose status could
    not be read is `unchecked`, not `complete`.
  * Only a completed, successful download of an immutable identity is cached.
    A partial, failed or in-progress fetch is re-fetched next time.

Examples:

    python3 ci_logs.py capture --repo owner/name --run 12345 --job 67890
    python3 ci_logs.py capture --from-file ./saved-job.log
    python3 ci_logs.py snippet --handle gha-<id>
    python3 ci_logs.py snippet --handle gha-<id> --pattern 'AssertionError' --context 5
    python3 ci_logs.py snippet --handle gha-<id> --lines 4100-4140
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = 1
HARD_LIMIT = 16_384
MIN_LIMIT = 512
DEFAULT_CONTEXT = 3
DEFAULT_TAIL = 8
DEFAULT_MAX_BLOCKS = 12
DEFAULT_MAX_LINE_BYTES = 2_048
SCAN_BYTES = 65_536
MAX_TRACKED_HITS = 5_000
STDERR_EXCERPT_BYTES = 512
CHUNK = 65_536

STRUCTURAL_MARKERS = (
    "##[error]",
    "::error",
    "npm ERR!",
    "Traceback (most recent call last)",
    "AssertionError",
    "FAILED",
    "FAIL:",
    "make: *** ",
    "Error: ",
    "error: ",
    "Segmentation fault",
    "panic: ",
    "fatal: ",
)


def json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_and_size(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError as exc:
        sys.stderr.write(f"ci_logs: chmod dir failed for {path}: {exc}\n")


def write_private(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def harden(path: Path) -> None:
    try:
        path.chmod(0o600)
    except OSError as exc:
        sys.stderr.write(f"ci_logs: chmod file failed for {path}: {exc}\n")


def clip_utf8(text: str, max_bytes: int) -> tuple[str, int]:
    """Cut `text` to at most `max_bytes` UTF-8 bytes on a character boundary."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text, 0
    if max_bytes <= 0:
        return "", len(encoded)
    cut = encoded[:max_bytes]
    while cut and (cut[-1] & 0xC0) == 0x80:
        cut = cut[:-1]
    if cut and cut[-1] >= 0xC0:
        cut = cut[:-1]
    return cut.decode("utf-8", "ignore"), len(encoded) - len(cut)


def decode_line(raw: bytes) -> str:
    return raw.decode("utf-8", "replace").replace("\r", "")


def iter_lines(handle, keep_bytes: int) -> Iterator[tuple[int, bytes, int]]:
    """Yield (line number, leading bytes, full byte length) without buffering a whole line."""
    lineno = 1
    prefix = bytearray()
    length = 0
    while True:
        chunk = handle.read(CHUNK)
        if not chunk:
            break
        start = 0
        while True:
            index = chunk.find(b"\n", start)
            if index == -1:
                segment = chunk[start:]
                length += len(segment)
                if len(prefix) < keep_bytes:
                    prefix.extend(segment[: keep_bytes - len(prefix)])
                break
            segment = chunk[start:index]
            length += len(segment)
            if len(prefix) < keep_bytes:
                prefix.extend(segment[: keep_bytes - len(prefix)])
            yield lineno, bytes(prefix), length
            lineno += 1
            prefix = bytearray()
            length = 0
            start = index + 1
    if length:
        yield lineno, bytes(prefix), length


def artifact_dir(root: Path, handle: str) -> Path:
    return root / "ci-logs" / handle


def identity_handle(prefix: str, parts: tuple[str, ...]) -> str:
    return f"{prefix}-{sha256_bytes('|'.join(parts).encode('utf-8'))[:32]}"


def load_manifest(directory: Path) -> dict[str, Any] | None:
    path = directory / "manifest.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        if path.exists():
            sys.stderr.write(f"ci_logs: manifest unreadable at {path}: {exc}\n")
        return None


def cached_artifact(directory: Path) -> dict[str, Any] | None:
    """A cache hit only when the manifest says complete and the bytes still agree."""
    manifest = load_manifest(directory)
    if not manifest or manifest.get("completeness") != "complete":
        return None
    log_path = directory / "log.txt"
    try:
        digest, size = hash_and_size(log_path)
    except OSError as exc:
        sys.stderr.write(f"ci_logs: cached log unreadable at {log_path}: {exc}\n")
        return None
    recorded = manifest.get("log") or {}
    if digest != recorded.get("sha256") or size != recorded.get("bytes"):
        sys.stderr.write(f"ci_logs: cached log at {log_path} does not match its manifest; refetching\n")
        return None
    return manifest


def write_manifest(directory: Path, manifest: dict[str, Any]) -> Path:
    """Record the manifest's own location inside it, so a reload carries it too."""
    path = directory / "manifest.json"
    manifest["manifest_path"] = str(path)
    write_private(path, json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8") + b"\n")
    return path


def staging_dir(root: Path) -> Path:
    ensure_private_dir(root)
    return Path(tempfile.mkdtemp(prefix=f"ci-logs-{uuid.uuid4().hex[:8]}-", dir=str(root)))


def drop_staging(staging: Path) -> None:
    try:
        for child in sorted(staging.iterdir()):
            try:
                child.unlink()
            except OSError as exc:
                sys.stderr.write(f"ci_logs: staging cleanup failed for {child}: {exc}\n")
        staging.rmdir()
    except OSError as exc:
        sys.stderr.write(f"ci_logs: staging rmdir failed for {staging}: {exc}\n")


def run_gh(gh_path: str, endpoint: str, out_path: Path, err_path: Path) -> tuple[int, int]:
    argv = [gh_path, "api", "-H", "Accept: application/vnd.github+json", endpoint]
    started = time.time()
    with out_path.open("wb") as out_handle, err_path.open("wb") as err_handle:
        process = subprocess.Popen(
            argv,
            stdout=out_handle,
            stderr=err_handle,
            stdin=subprocess.DEVNULL,
        )
        status = process.wait()
    return status, int((time.time() - started) * 1000)


def read_job_status(gh_path: str, repo: str, job: str, staging: Path) -> tuple[str, str | None, list[str]]:
    out_path = staging / "job.json"
    err_path = staging / "job.err"
    notes: list[str] = []
    try:
        status, _ = run_gh(gh_path, f"repos/{repo}/actions/jobs/{job}", out_path, err_path)
    except OSError as exc:
        notes.append(f"job status unchecked: cannot run {gh_path}: {exc}")
        return "unknown", None, notes
    if status != 0:
        detail, _ = clip_utf8(err_path.read_bytes().decode("utf-8", "replace").strip(), STDERR_EXCERPT_BYTES)
        notes.append(f"job status unchecked: gh exited {status}: {detail}")
        return "unknown", None, notes
    try:
        meta = json.loads(out_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        notes.append(f"job status unchecked: metadata unparsable: {exc}")
        return "unknown", None, notes
    return str(meta.get("status") or "unknown"), meta.get("conclusion"), notes


def finalize_artifact(
    directory: Path,
    staging: Path,
    log_name: str,
    err_name: str,
) -> tuple[Path, Path, str, int, str, int]:
    ensure_private_dir(directory)
    log_path = directory / "log.txt"
    err_path = directory / "stderr.log"
    os.replace(staging / log_name, log_path)
    os.replace(staging / err_name, err_path)
    harden(log_path)
    harden(err_path)
    log_hash, log_bytes = hash_and_size(log_path)
    err_hash, err_bytes = hash_and_size(err_path)
    return log_path, err_path, log_hash, log_bytes, err_hash, err_bytes


def capture_github(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    attempt = args.attempt
    identity = {
        "source": "github-actions",
        "repo": args.repo,
        "run_id": str(args.run),
        "attempt": attempt,
        "job_id": str(args.job),
    }
    handle = identity_handle(
        "gha", ("github-actions", args.repo, str(args.run), str(attempt), str(args.job))
    )
    directory = artifact_dir(root, handle)
    notes: list[str] = []

    if not args.refresh:
        manifest = cached_artifact(directory)
        if manifest:
            return artifact_response(manifest, cached=True, downloaded=False, notes=notes)

    staging = staging_dir(root)
    try:
        job_status, conclusion, status_notes = read_job_status(args.gh_path, args.repo, str(args.job), staging)
        notes.extend(status_notes)
        log_out = staging / "log.txt"
        log_err = staging / "stderr.log"
        try:
            producer_status, duration_ms = run_gh(
                args.gh_path, f"repos/{args.repo}/actions/jobs/{args.job}/logs", log_out, log_err
            )
        except OSError as exc:
            drop_staging(staging)
            return error_response(f"cannot run {args.gh_path}: {exc}")
        paths = finalize_artifact(directory, staging, "log.txt", "stderr.log")
    finally:
        if staging.exists():
            drop_staging(staging)

    log_path, err_path, log_hash, log_bytes, err_hash, err_bytes = paths
    completeness, why = judge_completeness(producer_status, job_status, log_bytes)
    if why:
        notes.append(why)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "handle": handle,
        "identity": identity,
        "job": {"status": job_status, "conclusion": conclusion},
        "producer": {
            "command": [args.gh_path, "api", f"repos/{args.repo}/actions/jobs/{args.job}/logs"],
            "exit_status": producer_status,
            "duration_ms": duration_ms,
        },
        "log": {"path": str(log_path), "bytes": log_bytes, "sha256": log_hash},
        "stderr": {"path": str(err_path), "bytes": err_bytes, "sha256": err_hash},
        "completeness": completeness,
        "notes": notes,
    }
    write_manifest(directory, manifest)
    return artifact_response(manifest, cached=False, downloaded=True, notes=[])


def judge_completeness(producer_status: int, job_status: str, log_bytes: int) -> tuple[str, str]:
    if producer_status != 0:
        return "incomplete", f"log fetch exited {producer_status}; bytes on disk may be partial"
    if job_status == "unknown":
        return "unchecked", "job status could not be read, so completeness is unchecked and not cached"
    if job_status != "completed":
        return "incomplete", f"job status is {job_status}, so the log is still being written"
    if log_bytes == 0:
        return "incomplete", "log fetch returned zero bytes"
    return "complete", ""


def capture_local(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    source = Path(args.from_file).expanduser()
    staging = staging_dir(root)
    try:
        log_out = staging / "log.txt"
        err_out = staging / "stderr.log"
        try:
            with source.open("rb") as reader, log_out.open("wb") as writer:
                for chunk in iter(lambda: reader.read(CHUNK), b""):
                    writer.write(chunk)
        except OSError as exc:
            return error_response(f"cannot read {source}: {exc}")
        err_out.write_bytes(b"")
        source_hash, source_bytes = hash_and_size(log_out)
        handle = identity_handle("local", ("local-file", source_hash))
        directory = artifact_dir(root, handle)
        paths = finalize_artifact(directory, staging, "log.txt", "stderr.log")
    finally:
        if staging.exists():
            drop_staging(staging)

    log_path, err_path, log_hash, log_bytes, err_hash, err_bytes = paths
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "handle": handle,
        "identity": {
            "source": "local-file",
            "path": str(source.resolve()),
            "source_sha256": source_hash,
            "source_bytes": source_bytes,
        },
        "job": {"status": "imported", "conclusion": None},
        "producer": {"command": ["import", str(source)], "exit_status": 0, "duration_ms": 0},
        "log": {"path": str(log_path), "bytes": log_bytes, "sha256": log_hash},
        "stderr": {"path": str(err_path), "bytes": err_bytes, "sha256": err_hash},
        "completeness": "complete",
        "notes": [],
    }
    write_manifest(directory, manifest)
    return artifact_response(manifest, cached=False, downloaded=False, notes=[])


def artifact_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    log = manifest.get("log") or {}
    err = manifest.get("stderr") or {}
    job = manifest.get("job") or {}
    completeness = manifest.get("completeness", "unchecked")
    return {
        "handle": manifest.get("handle"),
        "identity": manifest.get("identity"),
        "log_path": log.get("path"),
        "log_bytes": log.get("bytes"),
        "log_sha256": log.get("sha256"),
        "stderr_path": err.get("path"),
        "stderr_bytes": err.get("bytes"),
        "stderr_sha256": err.get("sha256"),
        "manifest_path": manifest.get("manifest_path"),
        "completeness": completeness,
        "complete": completeness == "complete",
        "producer_exit_status": (manifest.get("producer") or {}).get("exit_status"),
        "job_status": job.get("status"),
        "job_conclusion": job.get("conclusion"),
    }


def stderr_excerpt(manifest: dict[str, Any]) -> str:
    path = (manifest.get("stderr") or {}).get("path")
    if not path:
        return ""
    try:
        with open(path, "rb") as handle:
            head = handle.read(STDERR_EXCERPT_BYTES * 2)
    except OSError as exc:
        return f"stderr unreadable: {exc}"
    text, clipped = clip_utf8(head.decode("utf-8", "replace").strip(), STDERR_EXCERPT_BYTES)
    return text + (f" [+{clipped} bytes omitted]" if clipped else "")


def artifact_response(manifest: dict[str, Any], cached: bool, downloaded: bool, notes: list[str]) -> dict[str, Any]:
    summary = artifact_summary(manifest)
    errors: list[str] = []
    status = "ok"
    if summary["completeness"] != "complete":
        status = "incomplete"
        excerpt = stderr_excerpt(manifest)
        if excerpt:
            errors.append(f"producer stderr: {excerpt}")
    if summary["producer_exit_status"]:
        errors.append(f"producer exited {summary['producer_exit_status']}")
    return {
        "schema_version": SCHEMA_VERSION,
        "command": "capture",
        "status": status,
        "artifact": summary,
        "cached": cached,
        "downloaded": downloaded,
        "errors": errors,
        "notes": list(notes) + list(manifest.get("notes") or []),
        "instruction": (
            "Query bounded excerpts with: ci_logs.py snippet --artifact-root <root> "
            f"--handle {summary['handle']}. Do not read the artifact unbounded."
        ),
    }


def error_response(message: str, command: str = "capture") -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "status": "error",
        "artifact": None,
        "cached": False,
        "downloaded": False,
        "errors": [message],
        "notes": [],
        "instruction": "Fix the invocation; no artifact was produced.",
    }


def snippet_error(message: str, handle: str | None, limit: int = HARD_LIMIT) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "command": "snippet",
        "status": "error",
        "no_match": False,
        "artifact": {"handle": handle},
        "selection": {},
        "matches": {},
        "blocks": [],
        "omitted": {"blocks": 0, "lines": 0, "clipped_bytes": 0},
        "response_truncated": False,
        "limit": limit,
        "limit_clamped": False,
        "warnings": [],
        "errors": [message],
    }


def merge_blocks(hits: list[int], context: int, total: int) -> list[tuple[int, int]]:
    blocks: list[tuple[int, int]] = []
    for hit in hits:
        start = max(1, hit - context)
        end = min(total, hit + context)
        if blocks and start <= blocks[-1][1] + 1:
            blocks[-1] = (blocks[-1][0], max(blocks[-1][1], end))
        else:
            blocks.append((start, end))
    return blocks


def scan(log_path: Path, patterns: list[str]) -> dict[str, Any]:
    structural = 0
    matched = 0
    hits: list[int] = []
    unscanned = 0
    total = 0
    with log_path.open("rb") as handle:
        for lineno, prefix, length in iter_lines(handle, SCAN_BYTES):
            total = lineno
            if length > len(prefix):
                unscanned += 1
            text = decode_line(prefix)
            if patterns:
                if any(needle in text for needle in patterns):
                    matched += 1
                    if len(hits) < MAX_TRACKED_HITS:
                        hits.append(lineno)
            else:
                if any(marker in text for marker in STRUCTURAL_MARKERS):
                    structural += 1
                    if len(hits) < MAX_TRACKED_HITS:
                        hits.append(lineno)
    return {
        "total_lines": total,
        "structural": structural,
        "pattern": matched,
        "hits": hits,
        "unscanned": unscanned,
    }


def collect(log_path: Path, wanted: set[int], max_line_bytes: int) -> dict[int, tuple[str, int]]:
    out: dict[int, tuple[str, int]] = {}
    if not wanted:
        return out
    ceiling = max(wanted)
    with log_path.open("rb") as handle:
        for lineno, prefix, length in iter_lines(handle, SCAN_BYTES):
            if lineno in wanted:
                text, clipped = clip_utf8(decode_line(prefix), max_line_bytes)
                out[lineno] = (text, clipped + max(0, length - len(prefix)))
            if lineno >= ceiling:
                break
    return out


def fill_budget(envelope: dict[str, Any], ordered: list[dict[str, Any]], totals: dict[str, int], limit: int) -> dict[str, Any]:
    """Add whole lines until one more would push the serialized response over `limit`."""
    live: list[dict[str, Any]] = []
    accepted_lines = 0
    accepted_clipped = 0

    def render(blocks: list[dict[str, Any]], lines: int, clipped: int) -> bytes:
        envelope["blocks"] = sorted(
            [block for block in blocks if block["lines"]], key=lambda b: b["start_line"]
        )
        envelope["omitted"] = {
            "blocks": totals["blocks"] - len([b for b in blocks if b["lines"]]),
            "lines": totals["lines"] - lines,
            "clipped_bytes": clipped,
        }
        envelope["response_truncated"] = lines < totals["lines"]
        return json_bytes(envelope)

    if len(render([], 0, 0)) > limit:
        envelope["blocks"] = []
        envelope["omitted"] = {"blocks": totals["blocks"], "lines": totals["lines"], "clipped_bytes": 0}
        envelope["response_truncated"] = True
        envelope.setdefault("warnings", []).append(
            "response envelope alone exceeds the byte limit, so no excerpt fits; raise --limit"
        )
        return envelope

    stopped = False
    for candidate in ordered:
        if stopped:
            break
        block = {
            "kind": candidate["kind"],
            "start_line": candidate["start_line"],
            "end_line": candidate["end_line"],
            "lines": [],
        }
        live.append(block)
        for entry in candidate["entries"]:
            trial = dict(entry)
            block["lines"].append(trial)
            if len(render(live, accepted_lines + 1, accepted_clipped + trial["clipped_bytes"])) <= limit:
                accepted_lines += 1
                accepted_clipped += trial["clipped_bytes"]
                continue
            shrunk = shrink_to_fit(
                render, live, block, trial, accepted_lines, accepted_clipped, limit
            )
            if shrunk is None:
                block["lines"].pop()
                stopped = True
                break
            accepted_lines += 1
            accepted_clipped += shrunk
        block["start_line"] = block["lines"][0]["n"] if block["lines"] else candidate["start_line"]
        block["end_line"] = block["lines"][-1]["n"] if block["lines"] else candidate["end_line"]

    render(live, accepted_lines, accepted_clipped)
    return envelope


def shrink_to_fit(render, live, block, trial, accepted_lines, accepted_clipped, limit) -> int | None:
    """Clip the pending line down until the whole response fits, or give up on it."""
    original = trial["text"]
    original_clipped = trial["clipped_bytes"]
    low, high = 0, len(original.encode("utf-8"))
    best: int | None = None
    for _ in range(24):
        if low > high:
            break
        mid = (low + high) // 2
        text, dropped = clip_utf8(original, mid)
        trial["text"] = text
        trial["clipped_bytes"] = original_clipped + dropped
        if len(render(live, accepted_lines + 1, accepted_clipped + trial["clipped_bytes"])) <= limit:
            best = mid
            low = mid + 1
        else:
            high = mid - 1
    if best is None or best < 16:
        trial["text"] = original
        trial["clipped_bytes"] = original_clipped
        return None
    text, dropped = clip_utf8(original, best)
    trial["text"] = text
    trial["clipped_bytes"] = original_clipped + dropped
    return trial["clipped_bytes"]


def parse_range(value: str) -> tuple[int, int]:
    if "-" not in value:
        start = int(value)
        return start, start
    left, _, right = value.partition("-")
    return int(left), int(right)


def run_snippet(args: argparse.Namespace, root: Path, limit: int, adjustment: str) -> dict[str, Any]:
    directory = artifact_dir(root, args.handle)
    manifest = load_manifest(directory)
    if not manifest:
        return snippet_error(f"no readable artifact manifest at {directory}", args.handle, limit)
    log_path = Path((manifest.get("log") or {}).get("path") or (directory / "log.txt"))
    if not log_path.is_file() or not os.access(log_path, os.R_OK):
        return snippet_error(f"artifact log is missing or unreadable at {log_path}", args.handle, limit)

    patterns = list(args.pattern or [])
    if args.lines and patterns:
        return snippet_error("choose --lines or --pattern, not both", args.handle, limit)

    try:
        if args.lines:
            start, end = parse_range(args.lines)
        else:
            start = end = 0
    except ValueError:
        return snippet_error(f"--lines wants N or N-M, got {args.lines!r}", args.handle, limit)

    try:
        found = scan(log_path, patterns)
    except OSError as exc:
        return snippet_error(f"artifact log unreadable at {log_path}: {type(exc).__name__}: {exc}", args.handle, limit)

    total = found["total_lines"]
    mode = "range" if args.lines else ("pattern" if patterns else "structural")
    warnings: list[str] = []

    if mode == "range":
        clamped_start, clamped_end = max(1, start), min(total, end)
        ranges = [(clamped_start, clamped_end)] if clamped_start <= clamped_end else []
        blocks_total = len(ranges)
        no_match = not ranges
        if no_match:
            warnings.append(f"lines {start}-{end} lie outside the log's {total} lines")
    else:
        ranges = merge_blocks(found["hits"], args.context, total)
        blocks_total = len(ranges)
        no_match = found["pattern" if mode == "pattern" else "structural"] == 0
        if no_match and mode == "pattern":
            warnings.append(
                "no line contained any --pattern literal; absence of a match is not evidence the job passed"
            )
        if no_match and mode == "structural":
            warnings.append(
                "no structural failure marker matched; only the final-status tail is shown, and "
                "absence of a marker is not evidence the job passed"
            )

    kept = ranges[: args.max_blocks]
    omitted_block_ranges = ranges[args.max_blocks :]
    candidates = [
        {"kind": mode, "start_line": lo, "end_line": hi} for lo, hi in kept
    ]

    tail_start = max(1, total - args.tail + 1)
    if total and args.tail > 0:
        candidates.append({"kind": "final_status", "start_line": tail_start, "end_line": total})
        blocks_total += 1

    wanted: set[int] = set()
    for block in candidates:
        wanted.update(range(block["start_line"], block["end_line"] + 1))
    try:
        texts = collect(log_path, wanted, args.max_line_bytes)
    except OSError as exc:
        return snippet_error(f"artifact log unreadable at {log_path}: {exc}", args.handle, limit)

    selectable_lines = 0
    for block in candidates:
        entries = []
        for lineno in range(block["start_line"], block["end_line"] + 1):
            text, clipped = texts.get(lineno, ("", 0))
            entries.append({"n": lineno, "text": text, "clipped_bytes": clipped})
        block["entries"] = entries
        selectable_lines += len(entries)
    for lo, hi in omitted_block_ranges:
        selectable_lines += hi - lo + 1

    ordered = sorted(candidates, key=lambda b: (0 if b["kind"] == "final_status" else 1, b["start_line"]))

    completeness = manifest.get("completeness", "unchecked")
    if completeness != "complete":
        warnings.append(
            f"artifact completeness is {completeness}; excerpts may be missing evidence that was never captured"
        )
    if len(found["hits"]) >= MAX_TRACKED_HITS:
        warnings.append(
            f"only the first {MAX_TRACKED_HITS} matching lines were tracked for block selection; "
            "the counts in `matches` are still the true totals"
        )
    if found["unscanned"]:
        warnings.append(
            f"{found['unscanned']} line(s) exceed the {SCAN_BYTES}-byte scan window and were searched only in part"
        )
    note = limit_note(adjustment, limit)
    if note:
        warnings.append(note)

    status = "ok"
    if completeness != "complete":
        status = "incomplete"
    elif no_match:
        status = "no_match"

    envelope: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "command": "snippet",
        "status": status,
        "no_match": no_match,
        "artifact": dict(artifact_summary(manifest), total_lines=total),
        "selection": {
            "mode": mode,
            "patterns": patterns,
            "lines": args.lines,
            "context": args.context,
            "tail": args.tail,
            "max_blocks": args.max_blocks,
            "max_line_bytes": args.max_line_bytes,
        },
        "matches": {
            "structural": found["structural"],
            "pattern": found["pattern"],
            "blocks_total": blocks_total,
            "lines_total": total,
            "lines_unscanned": found["unscanned"],
            "hits_tracked": len(found["hits"]),
        },
        "blocks": [],
        "omitted": {"blocks": 0, "lines": 0, "clipped_bytes": 0},
        "response_truncated": False,
        "limit": limit,
        "limit_clamped": adjustment == "clamped",
        "warnings": warnings,
        "errors": [],
    }
    if len(json_bytes(envelope)) > limit:
        envelope["artifact"].pop("identity", None)
        envelope["warnings"].append("artifact identity omitted so the response fits the byte limit")
    totals = {"blocks": blocks_total, "lines": selectable_lines}
    return fill_budget(envelope, ordered, totals, limit)


def emit(payload: dict[str, Any], limit: int) -> bool:
    """Print the response. Returns True when it had to be degraded to fit.

    A degraded response still carries the failure signal -- completeness,
    producer exit status, job conclusion -- because dropping those to save
    bytes is exactly how an excerpt turns a failure into a clean-looking
    result. Only the excerpt text is expendable.
    """
    raw = json_bytes(payload)
    if len(raw) <= limit:
        sys.stdout.buffer.write(raw + b"\n")
        return False
    artifact = payload.get("artifact") or {}
    compact = {
        "schema_version": SCHEMA_VERSION,
        "command": payload.get("command"),
        "status": "error",
        "no_match": payload.get("no_match", False),
        "artifact": {
            "handle": artifact.get("handle"),
            "completeness": artifact.get("completeness"),
            "producer_exit_status": artifact.get("producer_exit_status"),
            "job_conclusion": artifact.get("job_conclusion"),
            "log_sha256": artifact.get("log_sha256"),
        },
        "blocks": [],
        "errors": [
            f"the response needs more than the {limit}-byte budget; "
            "raise --limit or narrow the query. No excerpt was returned."
        ],
        "response_truncated": True,
    }
    raw = json_bytes(compact)
    if len(raw) > limit:
        raw = json_bytes(
            {
                "status": "error",
                "artifact": {"handle": artifact.get("handle")},
                "errors": [f"response does not fit {limit} bytes"],
                "response_truncated": True,
            }
        )
    sys.stdout.buffer.write(raw + b"\n")
    return True


def resolve_limit(requested: int) -> tuple[int, str]:
    """Callers may ask for less than the hard cap, never silently for more."""
    if requested > HARD_LIMIT:
        return HARD_LIMIT, "clamped"
    if requested < MIN_LIMIT:
        return MIN_LIMIT, "floored"
    return requested, ""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ci_logs.py",
        description=(
            "Capture a CI job log to disk once, then return bounded excerpts from it. "
            "Full bytes stay on disk; every response is capped at "
            f"{HARD_LIMIT} UTF-8 bytes including metadata."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "The exit status describes this query, not the CI job. Read\n"
            "artifact.producer_exit_status and artifact.job_conclusion for that.\n"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture = subparsers.add_parser(
        "capture",
        help="Download or import a CI log into a private artifact directory.",
        description=(
            "Stream a GitHub Actions job log (or a local file, for replay) to disk. "
            "The response carries identities, hashes, byte counts, producer exit status "
            "and completeness -- never log bytes. Only a completed, successful download "
            "of an immutable identity is cached."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  ci_logs.py capture --repo owner/name --run 12345 --job 67890\n"
            "  ci_logs.py capture --repo owner/name --run 12345 --attempt 2 --job 67890\n"
            "  ci_logs.py capture --from-file ./saved-job.log\n"
        ),
    )
    capture.add_argument("--artifact-root", default=default_root(), help="Artifact storage directory.")
    capture.add_argument("--repo", help="OWNER/NAME of the repository holding the run.")
    capture.add_argument("--run", help="Workflow run id (provenance and cache identity).")
    capture.add_argument("--attempt", type=int, default=1, help="Run attempt number (default 1).")
    capture.add_argument("--job", help="Job id whose log to fetch.")
    capture.add_argument("--from-file", help="Import an existing log file instead of fetching.")
    capture.add_argument("--gh-path", default="gh", help="Path to the gh CLI (default: gh on PATH).")
    capture.add_argument("--refresh", action="store_true", help="Ignore any cached artifact and fetch again.")
    capture.add_argument("--limit", type=int, default=HARD_LIMIT, help=f"Response byte cap (max {HARD_LIMIT}).")

    snippet = subparsers.add_parser(
        "snippet",
        help="Return bounded excerpts from an already-captured artifact.",
        description=(
            "Read a captured artifact from disk -- no network call -- and return excerpts. "
            "With no selector, returns structural failure blocks plus the final-status tail. "
            "A literal --pattern or an explicit --lines range selects instead. "
            "No match is reported as no_match, never as a clean result."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  ci_logs.py snippet --handle gha-<id>\n"
            "  ci_logs.py snippet --handle gha-<id> --pattern 'AssertionError' --context 5\n"
            "  ci_logs.py snippet --handle gha-<id> --lines 4100-4140\n"
        ),
    )
    snippet.add_argument("--artifact-root", default=default_root(), help="Artifact storage directory.")
    snippet.add_argument("--handle", required=True, help="Artifact handle returned by capture.")
    snippet.add_argument("--pattern", action="append", help="Literal substring to find (repeatable).")
    snippet.add_argument("--lines", help="Source line range to return, as N or N-M.")
    snippet.add_argument("--context", type=int, default=DEFAULT_CONTEXT, help="Lines of context around each hit.")
    snippet.add_argument("--tail", type=int, default=DEFAULT_TAIL, help="Final-status lines to always include.")
    snippet.add_argument("--max-blocks", type=int, default=DEFAULT_MAX_BLOCKS, help="Most blocks to return.")
    snippet.add_argument(
        "--max-line-bytes", type=int, default=DEFAULT_MAX_LINE_BYTES, help="Per-line byte cap before clipping."
    )
    snippet.add_argument("--limit", type=int, default=HARD_LIMIT, help=f"Response byte cap (max {HARD_LIMIT}).")
    return parser


def default_root() -> str:
    return os.path.join(tempfile.gettempdir(), "catstack-ci-logs")


def limit_note(adjustment: str, limit: int) -> str:
    if adjustment == "clamped":
        return f"--limit was clamped down to the hard cap of {HARD_LIMIT} bytes"
    if adjustment == "floored":
        return f"--limit was raised to the {limit}-byte floor a response envelope needs"
    return ""


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    limit, adjustment = resolve_limit(args.limit)
    root = Path(args.artifact_root).expanduser().resolve()

    if args.command == "capture":
        try:
            if args.from_file and (args.repo or args.job):
                payload = error_response("pass --from-file or the --repo/--run/--job trio, not both")
            elif args.from_file:
                payload = capture_local(args, root)
            elif args.repo and args.run and args.job:
                payload = capture_github(args, root)
            else:
                payload = error_response("need --from-file, or all of --repo, --run and --job")
        except OSError as exc:
            payload = error_response(f"capture failed: {type(exc).__name__}: {exc}")
        note = limit_note(adjustment, limit)
        if note:
            payload.setdefault("notes", []).append(note)
        if emit(payload, limit):
            return 2
        return {"ok": 0, "incomplete": 1}.get(payload["status"], 2)

    payload = run_snippet(args, root, limit, adjustment)
    if emit(payload, limit):
        return 2
    return {"ok": 0}.get(payload["status"], 1 if payload["status"] != "error" else 2)


if __name__ == "__main__":
    raise SystemExit(main())
