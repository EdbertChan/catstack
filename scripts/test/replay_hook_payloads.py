#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
RUNNER_DIR = REPO / "engine" / "hooks" / "_runner"
sys.path.insert(0, str(RUNNER_DIR))

from outcome import classify  # noqa: E402


SCRATCH_STATE_DIRS = {
    "CATSTACK_HOOK_METRICS_DIR": "metrics",
    "CATSTACK_LLM_JUDGE_STATE_DIR": "llm-judge",
    "CATSTACK_HOOK_REMINDER_STATE_DIR": "reminders",
    "CATSTACK_SPLIT_SCOPE_STATE_DIR": "split-scope",
    "HOOK_FRESHNESS_STATE_DIR": "hook-freshness",
}


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay recorded hook payloads through two command sets.")
    parser.add_argument("--payload-dir", required=True, help="Directory containing <event_uid>-<hook>.json files.")
    parser.add_argument("--fleet", action="append", default=[], metavar="HOOK=COMMAND", help="Fleet command for a hook.")
    parser.add_argument(
        "--dispatcher",
        action="append",
        default=[],
        metavar="HOOK=COMMAND",
        help="Dispatcher command for a hook.",
    )
    parser.add_argument("--json-out", help="Optional path for the JSON equivalence report.")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--cwd", default=os.getcwd())
    return parser.parse_args(argv)


def _command_map(values: list[str]) -> dict[str, list[str]]:
    commands: dict[str, list[str]] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"command spec must be HOOK=COMMAND: {value}")
        hook, command = value.split("=", 1)
        hook = hook.strip()
        if not hook or not command.strip():
            raise SystemExit(f"command spec must be HOOK=COMMAND: {value}")
        commands[hook] = shlex.split(command)
    return commands


def _payload_files(root: Path) -> list[Path]:
    return sorted(path for path in root.iterdir() if path.is_file() and path.name.endswith(".json"))


def _payload_meta(path: Path) -> tuple[str, str]:
    stem = path.name[: -len(".json")]
    if "-" not in stem:
        raise ValueError(f"payload filename must be <event_uid>-<hook>.json: {path.name}")
    event_uid, hook = stem.split("-", 1)
    if not event_uid or not hook:
        raise ValueError(f"payload filename must be <event_uid>-<hook>.json: {path.name}")
    return event_uid, hook


def _read_findings(path: Path) -> tuple[list[str], str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [], f"{type(exc).__name__}: {exc}"
    if not isinstance(payload, list) or not all(isinstance(item, str) for item in payload):
        return [], "expected JSON array of strings"
    return payload, None


def _stdout_json(stdout: bytes) -> dict[str, Any] | None:
    try:
        payload = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _context(stdout: bytes) -> str | None:
    payload = _stdout_json(stdout)
    if payload is None:
        return None
    for key in ("additional_context", "additionalContext", "message", "reason", "user_message", "systemMessage"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    hook_output = payload.get("hookSpecificOutput")
    if not isinstance(hook_output, dict):
        return None
    for key in (
        "additional_context",
        "additionalContext",
        "message",
        "reason",
        "user_message",
        "permissionDecisionReason",
    ):
        value = hook_output.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _scratch_env(root: Path, findings_file: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("CATSTACK_HOOK_PAYLOAD_DIR", None)
    env["HOME"] = str(root / "home")
    env["TMPDIR"] = str(root / "tmp")
    env["CATSTACK_HOOK_FINDINGS_FILE"] = str(findings_file)
    for name, dirname in SCRATCH_STATE_DIRS.items():
        env[name] = str(root / dirname)
    for dirname in ("home", "tmp", *SCRATCH_STATE_DIRS.values()):
        (root / dirname).mkdir(parents=True, exist_ok=True)
    return env


def _run_command(command: list[str], payload: bytes, scratch: Path, timeout: float, cwd: str) -> dict[str, Any]:
    scratch.mkdir(parents=True, exist_ok=True)
    findings_file = scratch / "findings.json"
    findings_file.write_text("[]", encoding="utf-8")
    proc = subprocess.run(
        command,
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_scratch_env(scratch, findings_file),
        cwd=cwd,
        timeout=timeout,
    )
    findings, findings_error = _read_findings(findings_file)
    outcome = classify(proc.returncode, proc.stdout, proc.stderr, False)
    result: dict[str, Any] = {
        "command": command,
        "exit_code": proc.returncode,
        "outcome": outcome,
        "block": outcome == "blocked",
        "context": _context(proc.stdout),
        "findings": findings,
        "stdout_sha256": hashlib.sha256(proc.stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(proc.stderr).hexdigest(),
        "stdout_text": proc.stdout.decode("utf-8", errors="replace"),
        "stderr_text": proc.stderr.decode("utf-8", errors="replace"),
    }
    if findings_error is not None:
        result["findings_error"] = findings_error
    return result


def _mismatches(fleet: dict[str, Any], dispatcher: dict[str, Any]) -> list[str]:
    fields = ("stdout_sha256", "stderr_sha256", "exit_code", "outcome", "block", "context", "findings")
    return [field for field in fields if fleet.get(field) != dispatcher.get(field)]


def _render_table(rows: list[dict[str, Any]]) -> str:
    lines = ["hook payload match stdout stderr exit outcome context block findings"]
    for row in rows:
        mismatches = set(row["mismatches"])
        values = [
            row["hook"],
            row["payload"],
            "match" if row["match"] else "mismatch",
            "ok" if "stdout_sha256" not in mismatches else "diff",
            "ok" if "stderr_sha256" not in mismatches else "diff",
            "ok" if "exit_code" not in mismatches else "diff",
            "ok" if "outcome" not in mismatches else "diff",
            "ok" if "context" not in mismatches else "diff",
            "ok" if "block" not in mismatches else "diff",
            "ok" if "findings" not in mismatches else "diff",
        ]
        lines.append(" ".join(values))
    return "\n".join(lines) + "\n"


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    payload_dir = Path(args.payload_dir)
    fleet_commands = _command_map(args.fleet)
    dispatcher_commands = _command_map(args.dispatcher)
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="catstack-hook-replay-") as scratch_root:
        scratch_base = Path(scratch_root)
        for payload_path in _payload_files(payload_dir):
            event_uid, hook = _payload_meta(payload_path)
            if hook not in fleet_commands or hook not in dispatcher_commands:
                missing = []
                if hook not in fleet_commands:
                    missing.append("fleet")
                if hook not in dispatcher_commands:
                    missing.append("dispatcher")
                rows.append(
                    {
                        "payload": payload_path.name,
                        "event_uid": event_uid,
                        "hook": hook,
                        "match": False,
                        "mismatches": [f"missing_{name}_command" for name in missing],
                    }
                )
                continue
            payload = payload_path.read_bytes()
            fleet = _run_command(
                fleet_commands[hook],
                payload,
                scratch_base / payload_path.stem / "fleet",
                args.timeout,
                args.cwd,
            )
            dispatcher = _run_command(
                dispatcher_commands[hook],
                payload,
                scratch_base / payload_path.stem / "dispatcher",
                args.timeout,
                args.cwd,
            )
            mismatches = _mismatches(fleet, dispatcher)
            rows.append(
                {
                    "payload": payload_path.name,
                    "event_uid": event_uid,
                    "hook": hook,
                    "match": not mismatches,
                    "mismatches": mismatches,
                    "fleet": fleet,
                    "dispatcher": dispatcher,
                }
            )
    return {"payload_dir": str(payload_dir), "match": all(row["match"] for row in rows), "rows": rows}


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    report = build_report(args)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sys.stdout.write(_render_table(report["rows"]))
    return 0 if report["match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
