#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from detect import DESTINATION_RE, Finding, block_message, evaluate


def _block(findings: list[Finding]) -> None:
    sys.stderr.write(block_message(findings) + "\n")
    sys.exit(2)


def _refuse_if_destination(text: str, reason: str) -> None:
    if DESTINATION_RE.search(text):
        _block([Finding("unchecked", "gh", reason)])
    sys.stderr.write(f"external-claim-gate: {reason}; no gh write named, allowing\n")


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        _refuse_if_destination(raw, f"the hook payload is not JSON ({exc})")
        return
    if not isinstance(payload, dict):
        _refuse_if_destination(raw, "the hook payload is not a JSON object")
        return
    if (payload.get("tool_name") or payload.get("toolName")) != "Bash":
        return
    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        _refuse_if_destination(raw, "the payload carries no readable command string")
        return
    cwd = payload.get("cwd") or os.getcwd()
    try:
        findings = evaluate(command, cwd)
    except Exception as exc:
        _refuse_if_destination(command, f"the detector failed ({exc!r})")
        return
    if findings:
        _block(findings)


if __name__ == "__main__":
    main()
