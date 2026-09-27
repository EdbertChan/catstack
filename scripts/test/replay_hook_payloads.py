#!/usr/bin/env python3
"""Replay recorded hook payloads against two detector command sets."""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


SCRATCH_ENV = {
    "CATSTACK_HOOK_METRICS_DIR": "metrics",
    "CATSTACK_HOOK_STATE_DIR": "state",
    "CATSTACK_HOOK_REMINDER_STATE_DIR": "reminders",
    "CATSTACK_REFLECT_STATE_DIR": "reflect",
    "XDG_CACHE_HOME": "cache",
    "TMPDIR": "tmp",
    "REFLECT_ON_THRASH_STATE_DIR": "reflect-on-thrash",
    "VERDICT_FLIP_WATCH_STATE_DIR": "verdict-flip-watch",
    "WRONG_CHECK_REFLECT_STATE_DIR": "wrong-check-reflect",
    "CATSTACK_UNVERIFIED_TAG_CHECK_STATE_DIR": "unverified-tag-check",
    "CATSTACK_LLM_JUDGE_STATE_DIR": "llm-judge",
}


def _args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("payload_dir")
    parser.add_argument("--fleet", required=True, help="JSON object mapping detector names to argv arrays")
    parser.add_argument("--dispatcher", required=True, help="JSON object mapping detector names to argv arrays")
    parser.add_argument("--report", required=True)
    parser.add_argument("--timeout", type=float, default=15.0)
    return parser.parse_args(argv)


def _commands(path: str) -> dict[str, list[str]]:
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read command set {path}: {exc}") from exc
    if not isinstance(value, dict) or not all(
        isinstance(name, str)
        and isinstance(command, list)
        and command
        and all(isinstance(arg, str) for arg in command)
        for name, command in value.items()
    ):
        raise ValueError(f"invalid command set {path}: expected detector-to-nonempty-argv map")
    return value


def _payloads(root: str, detector: str) -> list[Path]:
    suffix = f"-{detector}.json"
    try:
        return sorted(path for path in Path(root).iterdir() if path.is_file() and path.name.endswith(suffix))
    except OSError as exc:
        raise ValueError(f"could not list payload directory {root}: {exc}") from exc


def _scratch_env(root: Path, findings: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("CATSTACK_HOOK_PAYLOAD_DIR", None)
    env["HOME"] = str(root / "home")
    env["CATSTACK_HOOK_FINDINGS_FILE"] = str(findings)
    for name, relative in SCRATCH_ENV.items():
        path = root / relative
        path.mkdir(parents=True, exist_ok=True)
        env[name] = str(path)
    (root / "home").mkdir(parents=True, exist_ok=True)
    return env


def _context(stdout: bytes, stderr: bytes, exit_code: int) -> tuple[str, bool]:
    try:
        value = json.loads(stdout.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        value = None
    blocked = exit_code == 2
    context = stderr.decode("utf-8", errors="replace").strip() if blocked else ""
    if isinstance(value, dict):
        blocked = blocked or value.get("decision") == "block" or value.get("continue") is False
        hook_output = value.get("hookSpecificOutput")
        candidates = [value]
        if isinstance(hook_output, dict):
            blocked = blocked or hook_output.get("permissionDecision") == "deny"
            candidates.insert(0, hook_output)
        for candidate in candidates:
            for key in (
                "permissionDecisionReason",
                "additionalContext",
                "additional_context",
                "reason",
                "message",
                "user_message",
            ):
                text = candidate.get(key)
                if isinstance(text, str) and text:
                    context = text
                    return context, blocked
    return context, blocked


def _metric_findings(root: Path, detector: str) -> list[str]:
    path = root / SCRATCH_ENV["CATSTACK_HOOK_METRICS_DIR"] / "runs.jsonl"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        rule_ids = row.get("rule_ids") if isinstance(row, dict) and row.get("hook") == detector else None
        if isinstance(rule_ids, list) and all(isinstance(item, str) for item in rule_ids):
            return rule_ids
    return []


def _run(
    command: list[str], payload: bytes, root: Path, label: str, detector: str, timeout: float
) -> dict[str, object]:
    findings = root / f"{label}-findings.json"
    findings.write_text("[]\n", encoding="utf-8")
    env = _scratch_env(root, findings)
    timed_out = False
    try:
        completed = subprocess.run(
            command,
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            timeout=timeout,
        )
        stdout, stderr, exit_code = completed.stdout, completed.stderr, completed.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = exc.stdout or b""
        stderr = exc.stderr or b""
        exit_code = None
    try:
        parsed_findings = json.loads(findings.read_text(encoding="utf-8"))
        if not isinstance(parsed_findings, list) or not all(isinstance(item, str) for item in parsed_findings):
            raise ValueError("expected array of strings")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        parsed_findings = []
        stderr += f"replay: could not read findings {findings}: {exc}\n".encode()
    if not parsed_findings:
        parsed_findings = _metric_findings(root, detector)
    context, blocked = _context(stdout, stderr, -1 if exit_code is None else exit_code)
    return {
        "stdout_b64": base64.b64encode(stdout).decode("ascii"),
        "stderr_b64": base64.b64encode(stderr).decode("ascii"),
        "context": context,
        "blocked": blocked,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "findings": parsed_findings,
    }


def replay(
    payload_dir: str,
    fleet: dict[str, list[str]],
    dispatcher: dict[str, list[str]],
    timeout: float,
) -> dict[str, object]:
    detector_names = sorted(set(fleet) | set(dispatcher))
    rows: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="catstack-hook-replay-") as scratch:
        scratch_root = Path(scratch)
        fleet_root = scratch_root / "fleet"
        dispatcher_root = scratch_root / "dispatcher"
        for root in (fleet_root, dispatcher_root):
            root.mkdir()
        for detector in detector_names:
            paths = _payloads(payload_dir, detector)
            cases = []
            missing = []
            if detector not in fleet:
                missing.append("fleet command")
            if detector not in dispatcher:
                missing.append("dispatcher command")
            for index, path in enumerate(paths):
                payload = path.read_bytes()
                if missing:
                    break
                fleet_result = _run(
                    fleet[detector], payload, fleet_root, f"{detector}-{index}", detector, timeout
                )
                dispatcher_result = _run(
                    dispatcher[detector],
                    payload,
                    dispatcher_root,
                    f"{detector}-{index}",
                    detector,
                    timeout,
                )
                cases.append(
                    {
                        "payload": path.name,
                        "match": fleet_result == dispatcher_result,
                        "fleet": fleet_result,
                        "dispatcher": dispatcher_result,
                    }
                )
            errors = [*missing]
            if not paths:
                errors.append("no recorded payloads")
            rows.append(
                {
                    "detector": detector,
                    "payloads": len(paths),
                    "match": not errors and all(case["match"] for case in cases),
                    "errors": errors,
                    "cases": cases,
                }
            )
    return {
        "schema": "catstack.hook_replay.v1",
        "match": bool(rows) and all(row["match"] for row in rows),
        "detectors": rows,
    }


def _table(report: dict[str, object]) -> str:
    rows = report["detectors"]
    lines = [f"{'detector':<36} {'payloads':>8} verdict", f"{'-' * 36} {'-' * 8} {'-' * 8}"]
    for row in rows:
        verdict = "MATCH" if row["match"] else "MISMATCH"
        lines.append(f"{row['detector']:<36} {row['payloads']:>8} {verdict}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = _args(sys.argv[1:] if argv is None else argv)
    try:
        report = replay(args.payload_dir, _commands(args.fleet), _commands(args.dispatcher), args.timeout)
    except ValueError as exc:
        print(f"replay_hook_payloads: {exc}", file=sys.stderr)
        return 2
    try:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"replay_hook_payloads: could not write report {args.report}: {exc}", file=sys.stderr)
        return 2
    print(_table(report))
    return 0 if report["match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
