"""Runtime wrapper for hooks migrated to the shared SDK."""
from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable

from engine.hooks._sdk.events import append_events
from engine.hooks._sdk.finding import Finding
from engine.hooks._sdk.modes import effective_mode
from engine.hooks._sdk.render import render_response


def run_hook(hook: str, harness: str, detect: Callable[[dict], list[Finding]]) -> None:
    started = time.monotonic()
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            event = {}
    except Exception as exc:
        print(f"catstack-hook-error {hook}: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(0)

    try:
        findings = detect(event)
    except Exception as exc:
        print(f"catstack-hook-error {hook}: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(0)

    try:
        mode, mode_source = effective_mode(hook, event)
        duration_ms = int((time.monotonic() - started) * 1000)
        append_events(hook, harness, event, findings, mode, mode_source, duration_ms)
        hook_event_name = str(event.get("hook_event_name") or event.get("hookEventName") or "")
        stdout_text, stderr_text, exit_code = render_response(harness, hook_event_name, mode, findings)
    except Exception as exc:
        print(f"catstack-hook-error {hook}: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(0)

    if stdout_text:
        sys.stdout.write(stdout_text)
    if stderr_text:
        sys.stderr.write(stderr_text)
    sys.exit(exit_code)
