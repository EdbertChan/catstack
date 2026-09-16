#!/usr/bin/env python3
"""Run a shell command, keep full stdout/stderr on disk, return a bounded stub.

Over HARD_BODY_LIMIT UTF-8 bytes of combined stdout+stderr, the JSON response
contains no payload bytes. Under the limit, the bodies are included so small
commands keep working. Relevance is never chosen here — a parent agent must
spawn a subagent with the artifact path and a question.
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
from typing import Any


HARD_BODY_LIMIT = 16_384
SCHEMA_VERSION = 1


def sha256_file(path: Path) -> tuple[str, int]:
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
        sys.stderr.write(f"capture_tool_result: chmod dir failed for {path}: {exc}\n")


def write_private(path: Path, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def argv_forces_metadata(argv: list[str]) -> bool:
    lowered = [a.lower() for a in argv]
    if not lowered:
        return False
    if "gh" in lowered and "run" in lowered and "view" in lowered:
        if "--log" in lowered or "--log-failed" in lowered:
            return True
    return False


def emit(payload: dict[str, Any], limit: int) -> None:
    def dumps(obj: dict[str, Any]) -> bytes:
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    raw = dumps(payload)
    if len(raw) <= limit:
        sys.stdout.buffer.write(raw + (b"" if raw.endswith(b"\n") else b"\n"))
        return
    art = payload.get("artifact") if isinstance(payload.get("artifact"), dict) else {}
    compact = {
        "schema_version": SCHEMA_VERSION,
        "status": payload.get("status", "complete"),
        "artifact": {
            "handle": art.get("handle"),
            "stdout_path": art.get("stdout_path"),
            "stderr_path": art.get("stderr_path"),
            "stdout_bytes": art.get("stdout_bytes"),
            "stderr_bytes": art.get("stderr_bytes"),
            "stdout_sha256": art.get("stdout_sha256"),
            "stderr_sha256": art.get("stderr_sha256"),
            "producer_exit_status": art.get("producer_exit_status"),
            "complete": art.get("complete", False),
            "body_included": False,
            "body_limit": art.get("body_limit", limit),
        },
        "instruction": "Spawn a fresh read-only subagent with the artifact path and a question.",
        "errors": list(payload.get("errors") or [])[:1],
        "omitted_payload_bytes": payload.get("omitted_payload_bytes", art.get("stdout_bytes", 0) + art.get("stderr_bytes", 0)),
        "response_truncated": True,
    }
    raw = dumps(compact)
    if len(raw) > limit:
        shorter = {
            "status": compact["status"],
            "artifact": {
                "handle": art.get("handle"),
                "stdout_path": art.get("stdout_path"),
                "stderr_path": art.get("stderr_path"),
                "complete": art.get("complete", False),
                "body_included": False,
                "stdout_sha256": art.get("stdout_sha256"),
                "producer_exit_status": art.get("producer_exit_status"),
            },
            "omitted_payload_bytes": compact.get("omitted_payload_bytes"),
            "response_truncated": True,
            "instruction": "Use artifact paths via subagent.",
            "errors": compact.get("errors") or [],
        }
        raw = dumps(shorter)
        if len(raw) > limit:
            raise RuntimeError(f"compact stub {len(raw)} exceeds limit {limit}")
    sys.stdout.buffer.write(raw + (b"" if raw.endswith(b"\n") else b"\n"))


def run_capture(argv: list[str], artifact_root: Path, limit: int, force_metadata: bool) -> dict[str, Any]:
    ensure_private_dir(artifact_root)
    handle = str(uuid.uuid4())
    artifact_dir = artifact_root / "artifacts" / handle
    ensure_private_dir(artifact_dir)
    stdout_path = artifact_dir / "stdout.log"
    stderr_path = artifact_dir / "stderr.log"

    staging = Path(tempfile.mkdtemp(prefix="capture-", dir=str(artifact_root)))
    try:
        staging_out = staging / "stdout.log"
        staging_err = staging / "stderr.log"
        started = time.time()
        with staging_out.open("wb") as out_h, staging_err.open("wb") as err_h:
            proc = subprocess.Popen(
                argv,
                stdout=out_h,
                stderr=err_h,
                stdin=subprocess.DEVNULL,
            )
            exit_status = proc.wait()
        duration_ms = int((time.time() - started) * 1000)
        os.replace(staging_out, stdout_path)
        os.replace(staging_err, stderr_path)
        for path in (stdout_path, stderr_path):
            try:
                path.chmod(0o600)
            except OSError as exc:
                sys.stderr.write(f"capture_tool_result: chmod file failed for {path}: {exc}\n")
    finally:
        for child in list(staging.iterdir()):
            try:
                child.unlink()
            except OSError as exc:
                sys.stderr.write(f"capture_tool_result: staging cleanup failed for {child}: {exc}\n")
        try:
            staging.rmdir()
        except OSError as exc:
            sys.stderr.write(f"capture_tool_result: staging rmdir failed for {staging}: {exc}\n")

    out_hash, out_bytes = sha256_file(stdout_path)
    err_hash, err_bytes = sha256_file(stderr_path)
    combined = out_bytes + err_bytes
    force = force_metadata or argv_forces_metadata(argv)
    include_body = (not force) and combined <= limit

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "handle": handle,
        "argv": argv,
        "complete": True,
        "producer": {"exit_status": exit_status, "duration_ms": duration_ms},
        "files": {
            "stdout": {"path": str(stdout_path), "bytes": out_bytes, "sha256": out_hash},
            "stderr": {"path": str(stderr_path), "bytes": err_bytes, "sha256": err_hash},
        },
        "body_limit": limit,
        "force_metadata": force,
    }
    write_private(artifact_dir / "manifest.json", json.dumps(manifest, indent=2).encode("utf-8") + b"\n")

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "complete_with_body" if include_body else "complete",
        "artifact": {
            "handle": handle,
            "root": str(artifact_dir),
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
            "stdout_bytes": out_bytes,
            "stderr_bytes": err_bytes,
            "stdout_sha256": out_hash,
            "stderr_sha256": err_hash,
            "producer_exit_status": exit_status,
            "complete": True,
            "body_included": include_body,
            "body_limit": limit,
        },
        "instruction": (
            "Spawn a fresh read-only subagent with the artifact path and a question; count its tokens."
            if not include_body
            else "Small result included."
        ),
        "errors": [],
        "response_truncated": False,
    }
    if include_body:
        payload["stdout"] = stdout_path.read_bytes().decode("utf-8", "replace")
        payload["stderr"] = stderr_path.read_bytes().decode("utf-8", "replace")
    else:
        payload["omitted_payload_bytes"] = combined
    if exit_status != 0:
        payload["errors"].append(f"producer exited {exit_status}")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture full command output to disk and return a bounded JSON stub."
    )
    parser.add_argument(
        "--artifact-root",
        default=os.path.join(tempfile.gettempdir(), "catstack-tool-captures"),
        help="Directory for artifact storage (default: system temp).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=HARD_BODY_LIMIT,
        help=f"Max UTF-8 bytes of combined stdout+stderr to include in the stub (default {HARD_BODY_LIMIT}).",
    )
    parser.add_argument(
        "--force-metadata",
        action="store_true",
        help="Never include stdout/stderr bodies in the stub.",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Command to run after --",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    limit = args.limit
    if limit < 256:
        emit(
            {
                "status": "error",
                "errors": ["--limit must be at least 256"],
                "artifact": {"complete": False, "body_included": False},
            },
            4096,
        )
        return 2
    if not command:
        emit(
            {
                "status": "error",
                "errors": ["missing command after --"],
                "artifact": {"complete": False, "body_included": False},
            },
            limit if limit >= 256 else 4096,
        )
        return 2
    try:
        payload = run_capture(
            command,
            Path(args.artifact_root).expanduser().resolve(),
            limit,
            bool(args.force_metadata),
        )
    except OSError as exc:
        payload = {
            "status": "error",
            "errors": [f"capture failed: {exc}"],
            "artifact": {"complete": False, "body_included": False},
            "instruction": "Fix the capture helper or command invocation; do not paste unbounded output.",
        }
        emit(payload, limit)
        return 1
    emit(payload, limit)
    return 0 if payload.get("artifact", {}).get("producer_exit_status", 1) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
