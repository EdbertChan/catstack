from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Callable
from typing import NoReturn

from events import write_events
from finding import Finding
from followup import record_followups
from modes import effective_mode
from render import render


def run_hook(hook: str, harness: str, detect: Callable[[dict[str, object]], list[Finding]]) -> NoReturn:
    started = time.monotonic()
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"catstack-hook-error {hook}: JSONDecodeError: {exc}", file=sys.stderr)
        sys.exit(0)
    if not isinstance(event, dict):
        event = {}

    hook_event_name = _hook_event_name(event)
    try:
        findings = detect(event)
    except Exception as exc:
        duration_ms = _duration_ms(started)
        print(f"catstack-hook-error {hook}: {type(exc).__name__}: {exc}", file=sys.stderr)
        write_events(hook, harness, event, [], "off", "runtime", duration_ms, action="crashed")
        sys.exit(0)

    duration_ms = _duration_ms(started)
    mode, mode_source = effective_mode(hook, event)
    _write_findings_file(findings)
    rows = write_events(hook, harness, event, findings, mode, mode_source, duration_ms)
    record_followups(hook, harness, event, rows, mode, mode_source, duration_ms)
    stdout_text, stderr_text, exit_code = render(harness, hook_event_name, mode, findings)
    if stdout_text:
        sys.stdout.write(stdout_text)
    if stderr_text:
        sys.stderr.write(stderr_text)
    sys.exit(exit_code)


def _hook_event_name(event: dict[str, object]) -> str:
    for key in ("hook_event_name", "hookEventName", "event"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _duration_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _write_findings_file(findings: list[Finding]) -> None:
    path = os.environ.get("CATSTACK_HOOK_FINDINGS_FILE")
    if not path:
        return
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump([finding.rule_id for finding in findings], handle)
            handle.write("\n")
    except OSError:
        return
