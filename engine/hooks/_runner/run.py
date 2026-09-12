from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from outcome import classify


def _hooks_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _harness(hooks_root: str) -> str:
    for name in ("claude", "cursor", "codex"):
        if f"/.{name}/" in hooks_root:
            return name
    return "unknown"


def _stdin_fields(stdin: bytes) -> tuple[str | None, str | None]:
    try:
        payload = json.loads(stdin.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, None
    if not isinstance(payload, dict):
        return None, None
    session_id = payload.get("session_id")
    if session_id is None:
        session_id = payload.get("conversation_id")
    return payload.get("hook_event_name"), session_id


def _metrics_path() -> str:
    root = os.environ.get("CATSTACK_HOOK_METRICS_DIR")
    if not root:
        root = os.path.expanduser(os.path.join("~", ".cache", "catstack-hook-metrics"))
    return os.path.join(root, "runs.jsonl")


def _write_metrics(row: dict[str, object], path: str) -> bytes:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    except OSError as exc:
        return f"catstack-hook-metrics: could not write row to {path}: {exc}\n".encode()
    return b""


def _format_timeout(seconds: float) -> str:
    if seconds == int(seconds):
        return str(int(seconds))
    return str(seconds)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float)
    parser.add_argument("hook_script")
    parser.add_argument("args", nargs=argparse.REMAINDER)
    return parser.parse_args(argv)


def _row(
    hooks_root: str,
    hook: str,
    script: str,
    stdin: bytes,
    outcome: str,
    exit_code: int | None,
    started: float,
    stdout: bytes,
    stderr: bytes,
) -> dict[str, object]:
    event, session_id = _stdin_fields(stdin)
    return {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "harness": _harness(hooks_root),
        "hook": hook,
        "script": script,
        "event": event,
        "session_id": session_id,
        "outcome": outcome,
        "exit_code": exit_code,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "stdout_bytes": len(stdout),
        "stderr_tail": stderr.decode("utf-8", errors="replace")[-500:],
    }


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    started = time.monotonic()
    stdin = sys.stdin.buffer.read()
    hooks_root = _hooks_root()
    hook, script = args.hook_script.split("/", 1) if "/" in args.hook_script else (args.hook_script, "")
    script_path = os.path.join(hooks_root, hook, script)
    stdout = b""
    stderr = b""
    exit_code = 1
    timed_out = False

    if not script or not os.path.isfile(script_path):
        stderr = f"catstack-hook-runner: no such hook script: {script_path}\n".encode()
    else:
        proc = subprocess.Popen(
            [sys.executable, script_path, *args.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=os.getcwd(),
            env=os.environ.copy(),
        )
        try:
            stdout, stderr = proc.communicate(stdin, timeout=args.timeout)
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            timed_out = True
            stdout = b""
            stderr = (
                f"catstack-hook-runner: {args.hook_script} timed out after "
                f"{_format_timeout(args.timeout)}s\n"
            ).encode()
            exit_code = 1

    try:
        outcome = classify(exit_code, stdout, stderr, timed_out)
        row = _row(hooks_root, hook, script, stdin, outcome, exit_code, started, stdout, stderr)
        metrics_error = _write_metrics(row, _metrics_path())
    except Exception as exc:
        metrics_error = f"catstack-hook-metrics: could not record run: {type(exc).__name__}: {exc}\n".encode()
    sys.stdout.buffer.write(stdout)
    sys.stdout.buffer.flush()
    sys.stderr.buffer.write(stderr)
    sys.stderr.buffer.write(metrics_error)
    sys.stderr.buffer.flush()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
