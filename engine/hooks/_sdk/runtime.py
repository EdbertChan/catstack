from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Callable

from events import append_events
from finding import Finding
from followup import update_followups
from modes import effective_mode
import registry
from render import render_response


Detector = Callable[[dict[str, Any]], list[Finding]]


def _event_name(event: dict[str, Any]) -> str:
    return str(
        event.get("hook_event_name")
        or event.get("hookEventName")
        or event.get("event_name")
        or event.get("event")
        or event.get("type")
        or ""
    )


def _write_runner_findings(findings: list[Finding]) -> None:
    path = os.environ.get("CATSTACK_HOOK_FINDINGS_FILE")
    if not path:
        return
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump([finding.rule_id for finding in findings], handle)
    except OSError as exc:
        print(f"catstack-hook-error findings: could not write {path}: {exc}", file=sys.stderr)


def run_hook(
    hook: str,
    harness: str,
    detect: Detector,
    silent_response: str = "",
) -> None:
    started = time.monotonic()
    try:
        payload = json.load(sys.stdin)
        event = payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError:
        if silent_response:
            sys.stdout.write(silent_response)
        return

    try:
        findings = detect(event)
    except Exception as exc:
        print(f"catstack-hook-error {hook}: {type(exc).__name__}: {exc}", file=sys.stderr)
        if silent_response:
            sys.stdout.write(silent_response)
        sys.exit(0)
    _write_runner_findings(findings)

    duration_ms = int((time.monotonic() - started) * 1000)
    mode, mode_source = effective_mode(hook, event)
    stdout_text, stderr_text, exit_code = render_response(harness, _event_name(event), mode, findings)
    if not findings and silent_response:
        stdout_text = silent_response
    rows = append_events(
        event=event,
        harness=harness,
        hook=hook,
        mode=mode,
        mode_source=mode_source,
        findings=findings,
        duration_ms=duration_ms,
    )
    if rows:
        try:
            followup_window_checks = registry.load_registry().thresholds.followup_window_checks
            update_followups(
                event=event,
                harness=harness,
                hook=hook,
                mode=mode,
                mode_source=mode_source,
                rows=rows,
                followup_window_checks=followup_window_checks,
            )
        except Exception as exc:
            print(f"catstack-hook-error followup: {type(exc).__name__}: {exc}", file=sys.stderr)
    if stdout_text:
        sys.stdout.write(stdout_text)
    if stderr_text:
        sys.stderr.write(stderr_text)
    sys.exit(exit_code)
