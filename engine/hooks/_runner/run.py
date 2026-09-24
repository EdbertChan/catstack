from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from outcome import classify

MIN_PYTHON = (3, 11)
PYTHON_OVERRIDE_ENV = "CATSTACK_HOOK_PYTHON"
PYTHON_DIRS_ENV = "CATSTACK_HOOK_PYTHON_DIRS"
WELL_KNOWN_PYTHON_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", os.path.expanduser("~/.local/bin"))
REPLY_EVENTS = ("Stop", "SubagentStop")
FENCE = "```"
SKIP_MACHINE_DELIVERABLE = "machine-deliverable"
METRICS_MAX_BYTES_ENV = "CATSTACK_HOOK_METRICS_MAX_BYTES"
METRICS_KEEP_ENV = "CATSTACK_HOOK_METRICS_KEEP"
DEFAULT_METRICS_MAX_BYTES = 20 * 1024 * 1024
DEFAULT_METRICS_KEEP = 3


def machine_deliverable(text: object) -> bool:
    if not isinstance(text, str):
        return False
    body = text.strip()
    if body.startswith(FENCE) and body.endswith(FENCE) and len(body) > 2 * len(FENCE):
        first_newline = body.find("\n")
        if first_newline == -1:
            return False
        body = body[first_newline + 1 : -len(FENCE)]
        if FENCE in body:
            return False
    try:
        parsed = json.loads(body)
    except ValueError:
        return False
    return isinstance(parsed, (dict, list))


def _skip_reason(stdin: bytes) -> str | None:
    try:
        payload = json.loads(stdin.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("hook_event_name") not in REPLY_EVENTS:
        return None
    if machine_deliverable(payload.get("last_assistant_message")):
        return SKIP_MACHINE_DELIVERABLE
    return None


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


def _notify_meta(args: list[str]) -> bytes:
    try:
        payload = json.loads(args[-1]) if args else None
    except json.JSONDecodeError:
        payload = None
    if not isinstance(payload, dict):
        return b""
    return json.dumps({"hook_event_name": payload.get("type"), "session_id": payload.get("thread-id")}).encode()


def _metrics_path() -> str:
    root = os.environ.get("CATSTACK_HOOK_METRICS_DIR")
    if not root:
        root = os.path.expanduser(os.path.join("~", ".cache", "catstack-hook-metrics"))
    return os.path.join(root, "runs.jsonl")


def _positive_env(name: str, default: int) -> tuple[int, bytes]:
    raw = os.environ.get(name)
    if raw is None:
        return default, b""
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value < 1:
        return default, f"catstack-hook-metrics: ignoring {name}={raw!r}: not a positive integer, using {default}\n".encode()
    return value, b""


def _rotate_metrics(path: str) -> bytes:
    max_bytes, message = _positive_env(METRICS_MAX_BYTES_ENV, DEFAULT_METRICS_MAX_BYTES)
    keep, keep_message = _positive_env(METRICS_KEEP_ENV, DEFAULT_METRICS_KEEP)
    message += keep_message
    try:
        if os.path.getsize(path) < max_bytes:
            return message
    except (FileNotFoundError, NotADirectoryError):
        return message
    except OSError as exc:
        return message + f"catstack-hook-metrics: could not rotate {path}: {exc}\n".encode()
    for index in range(keep - 1, 0, -1):
        try:
            os.replace(f"{path}.{index}", f"{path}.{index + 1}")
        except FileNotFoundError:
            continue
        except OSError as exc:
            return message + f"catstack-hook-metrics: could not rotate {path}.{index}: {exc}\n".encode()
    try:
        os.replace(path, f"{path}.1")
    except FileNotFoundError:
        return message
    except OSError as exc:
        return message + f"catstack-hook-metrics: could not rotate {path}: {exc}\n".encode()
    return message


def _write_metrics(row: dict[str, object], path: str) -> bytes:
    message = _rotate_metrics(path)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    except OSError as exc:
        return message + f"catstack-hook-metrics: could not write row to {path}: {exc}\n".encode()
    return message


def _make_findings_file() -> str:
    fd, path = tempfile.mkstemp(prefix="catstack-hook-findings-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump([], handle)
    return path


def _read_rule_ids(path: str) -> tuple[list[str], bytes]:
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, list) or not all(isinstance(item, str) for item in payload):
            raise ValueError("expected JSON array of strings")
        return payload, b""
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return [], f"catstack-hook-error runner: could not read findings file {path}: {exc}\n".encode()


def _delete_findings_file(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        return
    except OSError:
        return


def _python_dirs(env: dict[str, str]) -> list[str]:
    pinned = env.get(PYTHON_DIRS_ENV)
    if pinned:
        return pinned.split(os.pathsep)
    return env.get("PATH", "").split(os.pathsep) + list(WELL_KNOWN_PYTHON_DIRS)


def _pick_python(version: tuple[int, ...], executable: str, dirs: list[str], env: dict[str, str]) -> str | None:
    override = env.get(PYTHON_OVERRIDE_ENV)
    if override and os.access(override, os.X_OK):
        return override
    if tuple(version[:2]) >= MIN_PYTHON:
        return executable
    for minor in range(20, MIN_PYTHON[1] - 1, -1):
        for folder in dirs:
            candidate = os.path.join(folder, f"python3.{minor}")
            if folder and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
    return None


def _format_timeout(seconds: float) -> str:
    if seconds == int(seconds):
        return str(int(seconds))
    return str(seconds)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--notify", action="store_true")
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
    rule_ids: list[str],
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
        "rule_ids": rule_ids,
        "stdout_bytes": len(stdout),
        "stderr_tail": stderr.decode("utf-8", errors="replace")[-500:],
    }


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    started = time.monotonic()
    stdin = b"" if args.notify else sys.stdin.buffer.read()
    meta = _notify_meta(args.args) if args.notify else stdin
    hooks_root = _hooks_root()
    hook, script = args.hook_script.split("/", 1) if "/" in args.hook_script else (args.hook_script, "")
    script_path = os.path.join(hooks_root, hook, script)
    stdout = b""
    stderr = b""
    exit_code = 1
    timed_out = False
    findings_path = _make_findings_file()
    findings_error = b""
    rule_ids: list[str] = []
    skipped = None if args.notify else _skip_reason(stdin)

    try:
        python = _pick_python(sys.version_info, sys.executable, _python_dirs(dict(os.environ)), dict(os.environ))
        if skipped is not None:
            exit_code = 0
        elif not script or not os.path.isfile(script_path):
            stderr = f"catstack-hook-runner: no such hook script: {script_path}\n".encode()
        elif python is None:
            stderr = (
                f"catstack-hook-runner: {args.hook_script} needs Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer; "
                f"the runner started on {sys.executable} ({sys.version.split()[0]}) and found no python3.N "
                f"(N >= {MIN_PYTHON[1]}) on PATH or in {', '.join(WELL_KNOWN_PYTHON_DIRS)}. "
                f"Set {PYTHON_OVERRIDE_ENV} to a newer interpreter.\n"
            ).encode()
        else:
            env = os.environ.copy()
            env["CATSTACK_HOOK_FINDINGS_FILE"] = findings_path
            proc = subprocess.Popen(
                [python, script_path, *args.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=os.getcwd(),
                env=env,
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
        rule_ids, findings_error = _read_rule_ids(findings_path)
    finally:
        _delete_findings_file(findings_path)

    try:
        outcome = classify(exit_code, stdout, stderr, timed_out)
        row = _row(hooks_root, hook, script, meta, outcome, exit_code, started, stdout, stderr, rule_ids)
        if skipped is not None:
            row["skipped"] = skipped
        metrics_error = _write_metrics(row, _metrics_path())
    except Exception as exc:
        metrics_error = f"catstack-hook-metrics: could not record run: {type(exc).__name__}: {exc}\n".encode()
    sys.stdout.buffer.write(stdout)
    sys.stdout.buffer.flush()
    sys.stderr.buffer.write(stderr)
    sys.stderr.buffer.write(findings_error)
    sys.stderr.buffer.write(metrics_error)
    sys.stderr.buffer.flush()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
