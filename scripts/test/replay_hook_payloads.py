#!/usr/bin/env python3
"""Replay recorded hook payloads against two command sets and compare verdicts."""
from __future__ import annotations

import argparse
import base64
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path


def _command(value: str) -> tuple[str, list[str]]:
    name, separator, command = value.partition("=")
    if not separator or not name or not command:
        raise argparse.ArgumentTypeError("commands must use DETECTOR=COMMAND")
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid command for {name}: {exc}") from exc
    if not argv:
        raise argparse.ArgumentTypeError(f"empty command for {name}")
    return name, argv


def _payloads(root: Path) -> list[tuple[str, bytes, Path]]:
    result = []
    for path in sorted(root.glob("*.json")):
        parts = path.stem.split("-", 1)
        if len(parts) != 2:
            continue
        result.append((parts[1], path.read_bytes(), path))
    return result


def _blocked(stdout: bytes, exit_code: int) -> bool:
    if exit_code == 2:
        return True
    try:
        value = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(value, dict) and (
        value.get("decision") == "block"
        or value.get("continue") is False
        or value.get("permission") == "deny"
        or isinstance(value.get("hookSpecificOutput"), dict)
        and value["hookSpecificOutput"].get("permissionDecision") == "deny"
    )


def _run(argv: list[str], payload: bytes, scratch: Path) -> dict[str, object]:
    scratch.mkdir(parents=True, exist_ok=True)
    findings = scratch / "findings.json"
    findings.write_text("[]", encoding="utf-8")
    env = os.environ.copy()
    env["CATSTACK_HOOK_METRICS_DIR"] = str(scratch / "metrics")
    env["CATSTACK_HOOK_STATE_DIR"] = str(scratch / "state")
    env["CATSTACK_HOOK_FINDINGS_FILE"] = str(findings)
    proc = subprocess.run(argv, input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    try:
        recorded_findings = json.loads(findings.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        recorded_findings = None
    if not isinstance(recorded_findings, list):
        recorded_findings = None
    return {
        "stdout": base64.b64encode(proc.stdout).decode("ascii"),
        "stderr": base64.b64encode(proc.stderr).decode("ascii"),
        "exit_code": proc.returncode,
        "blocked": _blocked(proc.stdout, proc.returncode),
        "findings": recorded_findings,
    }


def replay(payload_dir: Path, fleet: dict[str, list[str]], dispatcher: dict[str, list[str]]) -> dict[str, object]:
    rows = []
    with tempfile.TemporaryDirectory(prefix="catstack-hook-replay-") as temp:
        scratch_root = Path(temp)
        for detector, payload, path in _payloads(payload_dir):
            if detector not in fleet or detector not in dispatcher:
                rows.append({"detector": detector, "payload": path.name, "match": False, "error": "missing command"})
                continue
            left = _run(fleet[detector], payload, scratch_root / "fleet")
            right = _run(dispatcher[detector], payload, scratch_root / "dispatcher")
            comparable = {"stdout", "exit_code", "blocked", "findings"}
            rows.append({
                "detector": detector,
                "payload": path.name,
                "match": all(left[key] == right[key] for key in comparable),
                "fleet": left,
                "dispatcher": right,
            })
    return {"matched": sum(row["match"] for row in rows), "total": len(rows), "rows": rows}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload_dir", type=Path)
    parser.add_argument("--fleet", action="append", type=_command, required=True, metavar="DETECTOR=COMMAND")
    parser.add_argument("--dispatcher", action="append", type=_command, required=True, metavar="DETECTOR=COMMAND")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if not args.payload_dir.is_dir():
        parser.error(f"payload directory does not exist: {args.payload_dir}")
    report = replay(args.payload_dir, dict(args.fleet), dict(args.dispatcher))
    if args.report:
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("detector payload match")
    for row in report["rows"]:
        print(f"{row['detector']} {row['payload']} {'match' if row['match'] else 'mismatch'}")
    print(f"matched {report['matched']}/{report['total']}")
    return 0 if report["total"] and report["matched"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
