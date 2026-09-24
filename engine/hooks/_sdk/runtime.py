from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Callable
from typing import NoReturn

import followup
from events import write_events
from finding import Finding
from modes import effective_finding_modes
from render import render


def run_hook(
    hook: str,
    harness: str,
    detect: Callable[[dict[str, object]], list[Finding]],
    hook_event_name: str | None = None,
    json_error_detect: Callable[[str, BaseException], list[Finding]] | None = None,
    json_error_stderr: bool = True,
    warn_stderr: bool = False,
) -> NoReturn:
    started = time.monotonic()
    raw = sys.stdin.read()
    try:
        event = json.loads(raw)
    except json.JSONDecodeError as exc:
        event = {"hook_event_name": hook_event_name or ""}
        findings = json_error_detect(raw, exc) if json_error_detect is not None else []
        _write_findings_file(findings)
        if json_error_stderr and json_error_detect is None:
            print(f"catstack-hook-error {hook}: JSONDecodeError: hook payload is not JSON: {exc}", file=sys.stderr)
        duration_ms = _duration_ms(started)
        if findings:
            mode, mode_source, finding_modes = effective_finding_modes(hook, event, findings)
            event_rows = write_events(hook, harness, event, findings, finding_modes, mode_source, duration_ms)
            if event_rows:
                followup.update_followups(hook, harness, event, event_rows, mode, mode_source, sys.stderr)
            stdout_text, stderr_text, exit_code = render(harness, hook_event_name or "", mode, findings)
            if stdout_text:
                sys.stdout.write(stdout_text)
            if stderr_text:
                sys.stderr.write(stderr_text)
            sys.exit(exit_code)
        stdout_text, _stderr_text, _exit_code = render(harness, hook_event_name or "", "warn", [])
        if stdout_text:
            sys.stdout.write(stdout_text)
        sys.exit(0)
    if not isinstance(event, dict):
        if json_error_detect is not None:
            event = {"hook_event_name": hook_event_name or ""}
            findings = json_error_detect(raw, TypeError("the hook payload is not a JSON object"))
            _write_findings_file(findings)
            duration_ms = _duration_ms(started)
            if findings:
                mode, mode_source, finding_modes = effective_finding_modes(hook, event, findings)
                event_rows = write_events(hook, harness, event, findings, finding_modes, mode_source, duration_ms)
                if event_rows:
                    followup.update_followups(hook, harness, event, event_rows, mode, mode_source, sys.stderr)
                stdout_text, stderr_text, exit_code = render(harness, hook_event_name or "", mode, findings)
                if stdout_text:
                    sys.stdout.write(stdout_text)
                if stderr_text:
                    sys.stderr.write(stderr_text)
                sys.exit(exit_code)
            stdout_text, _stderr_text, _exit_code = render(harness, hook_event_name or "", "warn", [])
            if stdout_text:
                sys.stdout.write(stdout_text)
            sys.exit(0)
        else:
            event = {}
    if hook_event_name and not _hook_event_name(event):
        event["hook_event_name"] = hook_event_name

    hook_event_name = _hook_event_name(event)
    try:
        findings = detect(event)
    except Exception as exc:
        duration_ms = _duration_ms(started)
        _write_findings_file([])
        print(f"catstack-hook-error {hook}: {type(exc).__name__}: {exc}", file=sys.stderr)
        write_events(hook, harness, event, [], "off", "runtime", duration_ms, action="crashed")
        sys.exit(0)

    duration_ms = _duration_ms(started)
    mode, mode_source, finding_modes = effective_finding_modes(hook, event, findings)
    _write_findings_file(findings)
    event_rows = write_events(
        hook,
        harness,
        event,
        findings,
        finding_modes if findings else mode,
        mode_source,
        duration_ms,
    )
    if event_rows:
        followup.update_followups(hook, harness, event, event_rows, mode, mode_source, sys.stderr)
    stdout_text, stderr_text, exit_code = render(harness, hook_event_name, mode, findings, warn_stderr)
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
    except OSError as exc:
        print(f"catstack-hook-error findings: could not write {path}: {exc}", file=sys.stderr)
