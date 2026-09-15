from __future__ import annotations

import json
import sys
import time
from typing import Any, Callable

from events import append_events
from finding import Finding
from modes import effective_mode
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


def run_hook(hook: str, harness: str, detect: Detector) -> None:
    started = time.monotonic()
    try:
        payload = json.load(sys.stdin)
        event = payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError as exc:
        print(f"catstack-hook-error {hook}: JSONDecodeError: {exc}", file=sys.stderr)
        sys.exit(0)

    try:
        findings = detect(event)
    except Exception as exc:
        print(f"catstack-hook-error {hook}: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(0)

    duration_ms = int((time.monotonic() - started) * 1000)
    mode, mode_source = effective_mode(hook, event)
    stdout_text, stderr_text, exit_code = render_response(harness, _event_name(event), mode, findings)
    append_events(
        event=event,
        harness=harness,
        hook=hook,
        mode=mode,
        mode_source=mode_source,
        findings=findings,
        duration_ms=duration_ms,
    )
    if stdout_text:
        sys.stdout.write(stdout_text)
    if stderr_text:
        sys.stderr.write(stderr_text)
    sys.exit(exit_code)
