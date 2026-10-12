#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass

RUNNER_DIR = Path(__file__).resolve().parents[2] / "engine" / "hooks" / "_runner"
sys.path.insert(0, str(RUNNER_DIR))

import outcome  # noqa: E402

STATE_ENVS = (
    "CATSTACK_HOOK_REMINDER_STATE_DIR",
    "CATSTACK_NARROW_THE_SCOPE_STATE_DIR",
    "CATSTACK_LLM_JUDGE_STATE_DIR",
    "CATSTACK_UNVERIFIED_TAG_CHECK_STATE_DIR",
    "CATSTACK_BUILD_THE_LEVER_STATE_DIR",
    "CATSTACK_TAG_LEDGER_DIR",
    "CATSTACK_SPLIT_SCOPE_STATE_DIR",
)


@dataclass(frozen=True)
class CommandSpec:
    label: str
    command: str


def _parse_command_spec(raw: str) -> CommandSpec:
    label, sep, command = raw.partition("=")
    if not sep or not label or not command:
        raise argparse.ArgumentTypeError("expected LABEL=COMMAND")
    return CommandSpec(label, command)


def _read_json_object(raw: bytes) -> dict[str, object] | None:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _context(stdout: bytes) -> str:
    payload = _read_json_object(stdout)
    if payload is None:
        return stdout.decode("utf-8", errors="replace").strip()
    for key in ("additionalContext", "additional_context", "message", "reason", "user_message"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    hook_output = payload.get("hookSpecificOutput")
    if isinstance(hook_output, dict):
        for key in ("additionalContext", "permissionDecisionReason", "reason"):
            value = hook_output.get(key)
            if isinstance(value, str) and value:
                return value
    return ""


def _rule_ids(metrics_dir: Path, findings_path: Path) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []

    def add(values: object) -> None:
        if isinstance(values, list):
            for value in values:
                if isinstance(value, str) and value not in seen:
                    seen.add(value)
                    ordered.append(value)

    try:
        add(json.loads(findings_path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        pass
    runs = metrics_dir / "runs.jsonl"
    try:
        with runs.open(encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                if isinstance(row, dict):
                    add(row.get("rule_ids"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        pass
    return ordered


def _scratch_env(base: Path, side: str, label: str, payload_name: str) -> tuple[dict[str, str], Path, Path]:
    root = base / side / label / payload_name
    metrics_dir = root / "metrics"
    state_dir = root / "state"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    findings_path = root / "findings.json"
    findings_path.write_text("[]", encoding="utf-8")
    env = os.environ.copy()
    env["CATSTACK_HOOK_METRICS_DIR"] = str(metrics_dir)
    env["CATSTACK_HOOK_FINDINGS_FILE"] = str(findings_path)
    env.pop("CATSTACK_HOOK_PAYLOAD_DIR", None)
    for name in STATE_ENVS:
        env[name] = str(state_dir / name.lower())
    return env, metrics_dir, findings_path


def _run_command(spec: CommandSpec, payload: bytes, payload_name: str, side: str, scratch: Path, timeout: float) -> dict:
    env, metrics_dir, findings_path = _scratch_env(scratch, side, spec.label, payload_name)
    timed_out = False
    try:
        proc = subprocess.run(
            spec.command,
            shell=True,
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            timeout=timeout,
        )
        stdout = proc.stdout
        stderr = proc.stderr
        exit_code = proc.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = exc.stdout or b""
        stderr = (exc.stderr or b"") + f"replay_hook_payloads: timed out after {timeout}s\n".encode()
        exit_code = 1
    result = outcome.classify(exit_code, stdout, stderr, timed_out)
    return {
        "command": spec.command,
        "exit_code": exit_code,
        "outcome": result,
        "blocked": result == "blocked",
        "context": _context(stdout),
        "findings": _rule_ids(metrics_dir, findings_path),
        "stdout_b64": base64.b64encode(stdout).decode("ascii"),
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stdout_text": stdout.decode("utf-8", errors="replace"),
        "stderr_b64": base64.b64encode(stderr).decode("ascii"),
        "stderr_text": stderr.decode("utf-8", errors="replace"),
    }


def _by_label(specs: list[CommandSpec], name: str) -> dict[str, CommandSpec]:
    result: dict[str, CommandSpec] = {}
    for spec in specs:
        if spec.label in result:
            raise SystemExit(f"duplicate {name} label: {spec.label}")
        result[spec.label] = spec
    return result


def _comparison_keys(verdict: dict) -> dict:
    return {
        "exit_code": verdict["exit_code"],
        "blocked": verdict["blocked"],
        "context": verdict["context"],
        "findings": verdict["findings"],
        "stdout_b64": verdict["stdout_b64"],
    }


def _payload_files(payload_dir: Path) -> list[Path]:
    return sorted(path for path in payload_dir.glob("*.json") if path.is_file())


def _print_table(rows: list[dict]) -> None:
    print("payload detector verdict fleet_exit dispatcher_exit fleet_outcome dispatcher_outcome")
    for row in rows:
        verdict = "match" if row["match"] else "mismatch"
        print(
            f"{row['payload']} {row['detector']} {verdict} "
            f"{row['fleet']['exit_code']} {row['dispatcher']['exit_code']} "
            f"{row['fleet']['outcome']} {row['dispatcher']['outcome']}"
        )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload-dir", required=True)
    parser.add_argument("--fleet", action="append", type=_parse_command_spec, required=True)
    parser.add_argument("--dispatcher", action="append", type=_parse_command_spec, required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--report-json")
    parser.add_argument("--keep-scratch", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    payload_dir = Path(args.payload_dir)
    payloads = _payload_files(payload_dir)
    if not payloads:
        raise SystemExit(f"no recorded payloads in {payload_dir}")
    fleet = _by_label(args.fleet, "fleet")
    dispatcher = _by_label(args.dispatcher, "dispatcher")
    if set(fleet) != set(dispatcher):
        missing_dispatcher = sorted(set(fleet) - set(dispatcher))
        missing_fleet = sorted(set(dispatcher) - set(fleet))
        raise SystemExit(
            f"fleet/dispatcher labels differ: missing dispatcher={missing_dispatcher} missing fleet={missing_fleet}"
        )

    scratch = Path(tempfile.mkdtemp(prefix="catstack-hook-replay-"))
    rows: list[dict] = []
    try:
        for payload_path in payloads:
            payload = payload_path.read_bytes()
            for label in sorted(fleet):
                fleet_verdict = _run_command(fleet[label], payload, payload_path.name, "fleet", scratch, args.timeout)
                dispatcher_verdict = _run_command(
                    dispatcher[label], payload, payload_path.name, "dispatcher", scratch, args.timeout
                )
                rows.append(
                    {
                        "payload": payload_path.name,
                        "detector": label,
                        "match": _comparison_keys(fleet_verdict) == _comparison_keys(dispatcher_verdict),
                        "fleet": fleet_verdict,
                        "dispatcher": dispatcher_verdict,
                    }
                )
    finally:
        if args.keep_scratch:
            print(f"scratch={scratch}", file=sys.stderr)
        else:
            shutil.rmtree(scratch)

    report = {"payload_dir": str(payload_dir), "match": all(row["match"] for row in rows), "rows": rows}
    if args.report_json:
        with open(args.report_json, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
    _print_table(rows)
    return 0 if report["match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
