#!/usr/bin/env python3
"""Capture CI logs to disk and return bounded diagnostic snippets.

The helper keeps original log bytes in local artifacts. CLI responses are JSON
and are capped by UTF-8 byte length, including metadata.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any


HARD_RESPONSE_LIMIT = 16_384
SCHEMA_VERSION = 1
STRUCTURAL_PATTERNS = (
    b"Traceback",
    b"AssertionError",
    b"FAIL:",
    b"FAILED",
    b"ERROR:",
    b"error:",
    b"failed",
    b"exit status",
    b"Process exited with code",
)


class UserError(Exception):
    pass


class DropAuthOnCrossHostRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        old_host = urllib.parse.urlparse(req.full_url).netloc
        new_host = urllib.parse.urlparse(newurl).netloc
        if old_host != new_host:
            redirected.remove_header("Authorization")
        return redirected


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass


def write_private(path: Path, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)


def read_manifest(artifact_root: Path, handle: str) -> dict[str, Any]:
    manifest = artifact_root / "artifacts" / handle / "manifest.json"
    if not manifest.is_file():
        raise UserError(f"artifact handle not found: {handle}")
    with manifest.open("r", encoding="utf-8") as handle_file:
        return json.load(handle_file)


def manifest_path(artifact_root: Path, artifact_id: str) -> Path:
    return artifact_root / "artifacts" / artifact_id / "manifest.json"


def artifact_dir(artifact_root: Path, artifact_id: str) -> Path:
    return artifact_root / "artifacts" / artifact_id


def cache_path(artifact_root: Path, cache_key: str) -> Path:
    return artifact_root / "cache" / f"{cache_key}.json"


def atomic_publish(staging: Path, final: Path) -> None:
    ensure_private_dir(final.parent)
    if final.exists():
        shutil.rmtree(final)
    os.replace(staging, final)
    try:
        final.chmod(0o700)
    except OSError:
        pass


def copy_stream_to_file(src: Any, dest: Path) -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    total = 0
    fd = os.open(dest, flags, 0o600)
    with os.fdopen(fd, "wb") as out:
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            out.write(chunk)
    return total


def compact_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def trim_utf8(text: str, max_bytes: int) -> tuple[str, int]:
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text, 0
    if max_bytes <= 0:
        return "", len(raw)
    cut = raw[:max_bytes]
    while cut:
        try:
            return cut.decode("utf-8"), len(raw) - len(cut)
        except UnicodeDecodeError:
            cut = cut[:-1]
    return "", len(raw)


def trim_response_to_limit(payload: dict[str, Any], limit: int) -> bytes:
    payload = json.loads(json.dumps(payload, ensure_ascii=False))
    payload["response_limit_bytes"] = limit
    payload["response_truncated"] = False
    raw = compact_json(payload)
    if len(raw) <= limit:
        payload["response_bytes"] = len(raw)
        raw = compact_json(payload)
        if len(raw) <= limit:
            return raw

    payload["response_truncated"] = True
    raw = compact_json(payload)
    while len(raw) > limit:
        snippets = [s for s in payload.get("snippets", []) if s.get("excerpt")]
        if not snippets:
            break
        largest = max(snippets, key=lambda item: len(item["excerpt"].encode("utf-8")))
        current = largest["excerpt"]
        target = max(0, len(current.encode("utf-8")) - (len(raw) - limit) - 128)
        trimmed, omitted = trim_utf8(current, target)
        largest["omitted_suffix_bytes"] = largest.get("omitted_suffix_bytes", 0) + omitted
        largest["excerpt"] = trimmed
        largest["excerpt_bytes"] = len(trimmed.encode("utf-8"))
        largest["byte_end"] = largest.get("byte_start", 0) + largest["excerpt_bytes"]
        largest["excerpt_truncated"] = True
        raw = compact_json(payload)
    if "message" in payload and isinstance(payload["message"], str):
        payload["message"], omitted = trim_utf8(payload["message"], 512)
        payload["message_omitted_bytes"] = omitted
    if "errors" in payload:
        payload["errors"] = [str(err)[:512] for err in payload["errors"][:3]]

    raw = compact_json(payload)
    if len(raw) <= limit:
        payload["response_bytes"] = len(raw)
        raw = compact_json(payload)
        return raw if len(raw) <= limit else compact_json(minimal_response(payload, limit))
    return compact_json(minimal_response(payload, limit))


def minimal_response(payload: dict[str, Any], limit: int) -> dict[str, Any]:
    minimal = {
        "status": payload.get("status", "error"),
        "artifact": payload.get("artifact"),
        "source": payload.get("source"),
        "response_limit_bytes": limit,
        "response_truncated": True,
        "message": "response metadata exceeded limit; artifact manifest on disk preserves details",
    }
    raw = compact_json(minimal)
    if len(raw) <= limit:
        return minimal
    return {
        "status": "error",
        "response_limit_bytes": limit,
        "response_truncated": True,
        "message": "response exceeded requested limit",
    }


def emit(payload: dict[str, Any], limit: int) -> int:
    if limit > HARD_RESPONSE_LIMIT:
        payload = {
            "status": "error",
            "message": f"requested limit {limit} exceeds hard maximum {HARD_RESPONSE_LIMIT}",
        }
        limit = HARD_RESPONSE_LIMIT
    data = trim_response_to_limit(payload, limit)
    sys.stdout.buffer.write(data + b"\n")
    return 0 if payload.get("status") in {"complete", "match", "no_match"} else 1


def build_manifest(
    *,
    artifact_id: str,
    source: dict[str, Any],
    stdout_path: Path,
    stderr_path: Path,
    producer_exit_status: int,
    complete: bool,
    status: str,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    stdout_hash, stdout_bytes = sha256_file(stdout_path)
    stderr_hash, stderr_bytes = sha256_file(stderr_path)
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_id": artifact_id,
        "source": source,
        "created_at_unix": int(time.time()),
        "complete": complete,
        "status": status,
        "producer": {"exit_status": producer_exit_status},
        "files": {
            "stdout": {
                "path": "stdout.log",
                "sha256": stdout_hash,
                "bytes": stdout_bytes,
            },
            "stderr": {
                "path": "stderr.log",
                "sha256": stderr_hash,
                "bytes": stderr_bytes,
            },
        },
        "errors": errors or [],
    }


def publish_artifact(
    artifact_root: Path,
    artifact_id: str,
    source: dict[str, Any],
    staging: Path,
    producer_exit_status: int,
    complete: bool,
    status: str,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    manifest = build_manifest(
        artifact_id=artifact_id,
        source=source,
        stdout_path=staging / "stdout.log",
        stderr_path=staging / "stderr.log",
        producer_exit_status=producer_exit_status,
        complete=complete,
        status=status,
        errors=errors,
    )
    write_private(staging / "manifest.json", json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"))
    atomic_publish(staging, artifact_dir(artifact_root, artifact_id))
    return manifest


def capture_local(args: argparse.Namespace) -> dict[str, Any]:
    artifact_root = args.artifact_root.resolve()
    source_path = args.file.resolve()
    source = {
        "type": "local",
        "path": str(source_path),
        "repo": args.repo,
        "run_id": args.run_id,
        "attempt": args.attempt,
        "job_id": args.job_id,
    }
    ensure_private_dir(artifact_root)
    staging = Path(tempfile.mkdtemp(prefix="ci-log-", dir=str(artifact_root)))
    try:
        write_private(staging / "stderr.log", b"")
        if args.stderr_file:
            shutil.copyfile(args.stderr_file, staging / "stderr.log")
        try:
            with source_path.open("rb") as src:
                copy_stream_to_file(src, staging / "stdout.log")
            complete = True
            status = "complete"
            errors: list[str] = []
        except OSError as exc:
            write_private(staging / "stdout.log", b"")
            complete = False
            status = "error"
            errors = [f"local import failed: {exc}"]
        stdout_hash, stdout_bytes = sha256_file(staging / "stdout.log")
        source["content_sha256"] = stdout_hash
        source["content_bytes"] = stdout_bytes
        identity = json.dumps(source, sort_keys=True, separators=(",", ":")).encode("utf-8")
        artifact_id = "local-" + sha256_bytes(identity)[:24]
        manifest = publish_artifact(
            artifact_root,
            artifact_id,
            source,
            staging,
            int(args.producer_exit_status),
            complete,
            status,
            errors,
        )
        return capture_response(manifest, cache_hit=False)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise


def github_identity(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "type": "github-actions",
        "api_url": args.api_url.rstrip("/"),
        "repo": args.repo,
        "run_id": str(args.run_id),
        "attempt": str(args.attempt),
        "job_id": str(args.job_id),
    }


def capture_github(args: argparse.Namespace) -> dict[str, Any]:
    artifact_root = args.artifact_root.resolve()
    ensure_private_dir(artifact_root)
    identity = github_identity(args)
    cache_key = sha256_bytes(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    cached = cache_path(artifact_root, cache_key)
    if cached.is_file():
        with cached.open("r", encoding="utf-8") as handle:
            cached_manifest_path = Path(json.load(handle)["manifest_path"])
        if cached_manifest_path.is_file():
            with cached_manifest_path.open("r", encoding="utf-8") as handle:
                manifest = json.load(handle)
            if manifest.get("complete") and manifest.get("status") == "complete":
                return capture_response(manifest, cache_hit=True)

    staging = Path(tempfile.mkdtemp(prefix="ci-log-", dir=str(artifact_root)))
    url = f"{args.api_url.rstrip('/')}/repos/{args.repo}/actions/jobs/{args.job_id}/logs"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "catstack-ci-log-helper",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get(args.token_env)
    if token:
        headers["Authorization"] = f"Bearer {token}"

    producer_status = 1
    complete = False
    status = "error"
    errors: list[str] = []
    try:
        request = urllib.request.Request(url, headers=headers)
        opener = urllib.request.build_opener(DropAuthOnCrossHostRedirect)
        with opener.open(request, timeout=args.timeout) as response:
            producer_status = int(getattr(response, "status", 0) or 0)
            written = copy_stream_to_file(response, staging / "stdout.log")
            expected_length = response.headers.get("Content-Length")
            if expected_length is not None and written != int(expected_length):
                raise IOError(f"download ended after {written} bytes; expected {expected_length}")
        write_private(staging / "stderr.log", b"")
        complete = True
        status = "complete"
        errors = []
    except urllib.error.HTTPError as exc:
        producer_status = exc.code
        if not (staging / "stdout.log").exists():
            write_private(staging / "stdout.log", b"")
        write_private(staging / "stderr.log", str(exc).encode("utf-8", "replace"))
        errors = [f"github log download failed with HTTP {exc.code}"]
    except Exception as exc:
        if not (staging / "stdout.log").exists():
            write_private(staging / "stdout.log", b"")
        write_private(staging / "stderr.log", str(exc).encode("utf-8", "replace"))
        errors = [f"github log download incomplete: {exc.__class__.__name__}: {exc}"]

    artifact_id = "gha-" + cache_key[:24] if complete else f"gha-{cache_key[:16]}-incomplete-{uuid.uuid4().hex[:8]}"
    download_exit_status = 0 if complete else (producer_status if not 200 <= producer_status < 400 else 1)
    manifest = publish_artifact(
        artifact_root,
        artifact_id,
        identity,
        staging,
        download_exit_status,
        complete,
        status,
        errors,
    )
    if complete and status == "complete":
        ensure_private_dir(cached.parent)
        write_private(
            cached,
            json.dumps({"manifest_path": str(manifest_path(artifact_root, artifact_id))}, sort_keys=True).encode("utf-8"),
        )
    return capture_response(manifest, cache_hit=False)


def capture_response(manifest: dict[str, Any], *, cache_hit: bool) -> dict[str, Any]:
    stdout_file = manifest["files"]["stdout"]
    return {
        "status": manifest["status"],
        "artifact": {
            "handle": manifest["artifact_id"],
            "complete": manifest["complete"],
            "stdout_sha256": stdout_file["sha256"],
            "stdout_bytes": stdout_file["bytes"],
            "producer_exit_status": manifest["producer"]["exit_status"],
            "cache_hit": cache_hit,
        },
        "source": manifest["source"],
        "errors": manifest.get("errors", []),
    }


def byte_line_ranges(data: bytes) -> list[tuple[int, int, bytes]]:
    ranges: list[tuple[int, int, bytes]] = []
    offset = 0
    for line in data.splitlines(keepends=True):
        end = offset + len(line)
        ranges.append((offset, end, line))
        offset = end
    if not ranges and data == b"":
        return []
    if offset < len(data):
        ranges.append((offset, len(data), data[offset:]))
    return ranges


def merge_line_windows(windows: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not windows:
        return []
    windows = sorted(windows)
    merged = [windows[0]]
    for start, end in windows[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end + 1:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def select_windows(lines: list[tuple[int, int, bytes]], args: argparse.Namespace) -> tuple[str, list[tuple[int, int]], int]:
    if args.line_start is not None:
        end = args.line_end if args.line_end is not None else args.line_start
        if args.line_start < 1 or end < args.line_start:
            raise UserError("invalid line range")
        return "line_range", [(args.line_start, end)], 0

    patterns = [args.pattern.encode("utf-8")] if args.pattern is not None else list(STRUCTURAL_PATTERNS)
    windows: list[tuple[int, int]] = []
    total_matches = 0
    for idx, (_, _, line) in enumerate(lines, start=1):
        if any(pattern in line for pattern in patterns):
            total_matches += 1
            if len(windows) < args.max_matches:
                windows.append((max(1, idx - args.context), min(len(lines), idx + args.context)))
    return ("literal_pattern" if args.pattern is not None else "structural_failure"), merge_line_windows(windows), total_matches


def build_snippets(
    data: bytes,
    *,
    windows: list[tuple[int, int]],
    limit: int,
) -> list[dict[str, Any]]:
    lines = byte_line_ranges(data)
    snippets: list[dict[str, Any]] = []
    for start_line, end_line in windows:
        selected = [entry for idx, entry in enumerate(lines, start=1) if start_line <= idx <= end_line]
        if not selected:
            continue
        byte_start = selected[0][0]
        byte_end = selected[-1][1]
        raw_excerpt = data[byte_start:byte_end]
        text = raw_excerpt.decode("utf-8", "replace")
        excerpt, omitted = trim_utf8(text, max(0, limit))
        kept_bytes = len(excerpt.encode("utf-8"))
        snippets.append(
            {
                "line_start": start_line,
                "line_end": end_line,
                "byte_start": byte_start,
                "byte_end": byte_start + kept_bytes,
                "original_byte_end": byte_end,
                "excerpt": excerpt,
                "excerpt_bytes": kept_bytes,
                "excerpt_sha256": sha256_bytes(raw_excerpt[:kept_bytes]),
                "excerpt_truncated": omitted > 0,
                "omitted_prefix_bytes": byte_start,
                "omitted_suffix_bytes": len(data) - byte_end + omitted,
            }
        )
    return snippets


def snippet(args: argparse.Namespace) -> dict[str, Any]:
    artifact_root = args.artifact_root.resolve()
    manifest = read_manifest(artifact_root, args.handle)
    stream = args.stream
    rel_path = manifest["files"][stream]["path"]
    log_path = artifact_dir(artifact_root, manifest["artifact_id"]) / rel_path
    if not log_path.is_file():
        raise UserError(f"artifact stream missing on disk: {stream}")
    data = log_path.read_bytes()
    lines = byte_line_ranges(data)
    selection, windows, match_count = select_windows(lines, args)
    snippet_budget = max(0, args.limit // 2)
    snippets = build_snippets(data, windows=windows, limit=snippet_budget)
    if args.pattern is not None and match_count == 0:
        status = "no_match"
    elif not snippets:
        status = "no_match"
    else:
        status = "match"
    return {
        "status": status,
        "artifact": {
            "handle": manifest["artifact_id"],
            "complete": manifest["complete"],
            "stdout_sha256": manifest["files"]["stdout"]["sha256"],
            "stdout_bytes": manifest["files"]["stdout"]["bytes"],
            "producer_exit_status": manifest["producer"]["exit_status"],
        },
        "source": manifest["source"],
        "selection": {
            "stream": stream,
            "mode": selection,
            "requested_pattern": args.pattern,
            "context_lines": args.context,
            "match_count": match_count,
            "returned_ranges": len(snippets),
            "omitted_match_count": max(0, match_count - len(windows)),
        },
        "snippets": snippets,
        "errors": [] if manifest["complete"] else manifest.get("errors", []),
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture CI logs to private local artifacts and query bounded snippets without re-downloading logs."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=HARD_RESPONSE_LIMIT,
        help=f"maximum UTF-8 bytes to write to stdout, metadata included (default and hard maximum: {HARD_RESPONSE_LIMIT})",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture_parser = subparsers.add_parser("capture", help="capture a CI log artifact")
    capture_sub = capture_parser.add_subparsers(dest="capture_source", required=True)

    local = capture_sub.add_parser("local", help="import an existing local log file for replay")
    local.add_argument("--artifact-root", type=Path, required=True, help="directory for private log artifacts")
    local.add_argument("--file", type=Path, required=True, help="local stdout log file to import")
    local.add_argument("--stderr-file", type=Path, help="optional local stderr file to import separately")
    local.add_argument("--producer-exit-status", type=int, default=0, help="exit status of the producer that made the log")
    local.add_argument("--repo", help="optional repository provenance")
    local.add_argument("--run-id", help="optional run identifier provenance")
    local.add_argument("--attempt", help="optional run attempt provenance")
    local.add_argument("--job-id", help="optional job identifier provenance")

    github = capture_sub.add_parser("github", help="download a GitHub Actions job log")
    github.add_argument("--artifact-root", type=Path, required=True, help="directory for private log artifacts")
    github.add_argument("--repo", required=True, help="repository in owner/name form")
    github.add_argument("--run-id", required=True, help="workflow run id")
    github.add_argument("--attempt", required=True, help="workflow run attempt")
    github.add_argument("--job-id", required=True, help="workflow job id")
    github.add_argument("--api-url", default="https://api.github.com", help="GitHub API base URL")
    github.add_argument("--token-env", default="GITHUB_TOKEN", help="environment variable containing a GitHub token")
    github.add_argument("--timeout", type=float, default=30.0, help="download timeout in seconds")

    snip = subparsers.add_parser("snippet", help="read a bounded excerpt from a local artifact")
    snip.add_argument("--artifact-root", type=Path, required=True, help="directory containing private log artifacts")
    snip.add_argument("--handle", required=True, help="artifact handle returned by capture")
    snip.add_argument("--stream", choices=("stdout", "stderr"), default="stdout", help="artifact stream to inspect")
    snip.add_argument("--line-start", type=int, help="1-based source line at which to start")
    snip.add_argument("--line-end", type=int, help="1-based source line at which to end")
    snip.add_argument("--pattern", help="literal UTF-8 pattern to search for")
    snip.add_argument("--context", type=int, default=2, help="context lines around pattern matches")
    snip.add_argument("--max-matches", type=int, default=5, help="maximum pattern windows to return")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    try:
        if args.limit < 512:
            raise UserError("limit must be at least 512 bytes")
        if args.command == "capture" and args.capture_source == "local":
            payload = capture_local(args)
        elif args.command == "capture" and args.capture_source == "github":
            payload = capture_github(args)
        elif args.command == "snippet":
            payload = snippet(args)
        else:
            raise UserError("unknown command")
    except UserError as exc:
        payload = {"status": "error", "message": str(exc)}
    return emit(payload, args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
