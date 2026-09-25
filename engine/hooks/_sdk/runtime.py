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
    json_error_stderr: bool = True,
    json_error_stderr_prefix: str | None = None,
) -> NoReturn:
    started = time.monotonic()
    raw = sys.stdin.read()
    try:
        event = json.loads(raw)
    except json.JSONDecodeError as exc:
        event = {
            "_raw_payload": raw,
            "_payload_error": f"the hook payload is not JSON ({exc})",
            "_payload_error_type": type(exc).__name__,
            "_payload_error_detail": str(exc),
        }
    if not isinstance(event, dict):
        event = {
            "_raw_payload": raw,
            "_payload_error": "the hook payload is not a JSON object",
        }
    else:
        event.setdefault("_raw_payload", raw)
    event.setdefault("_catstack_harness", harness)
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
    if event.get("_payload_error") and not findings:
        if json_error_stderr_prefix is not None:
            print(
                f"{json_error_stderr_prefix}: "
                f"{event.get('_payload_error_type', 'ValueError')}: "
                f"{event.get('_payload_error_detail', event['_payload_error'])}",
                file=sys.stderr,
            )
        elif json_error_stderr:
            print(f"{hook}: {event['_payload_error']}; no findings, allowing", file=sys.stderr)
    event_rows = _write_event_rows(hook, harness, event, findings, finding_modes, mode, mode_source, duration_ms)
    if event_rows:
        followup.update_followups(hook, harness, event, event_rows, mode, mode_source, sys.stderr)
    rendered_mode, rendered_findings = _renderable_findings(finding_modes, findings, mode)
    stdout_text, stderr_text, exit_code = render(harness, hook_event_name, rendered_mode, rendered_findings)
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


def _write_event_rows(
    hook: str,
    harness: str,
    event: dict[str, object],
    findings: list[Finding],
    finding_modes: list[tuple[Finding, str, str]],
    mode: str,
    mode_source: str,
    duration_ms: int,
) -> list[dict[str, object]]:
    if not findings:
        return write_events(hook, harness, event, [], mode, mode_source, duration_ms)
    rows: list[dict[str, object]] = []
    for finding, finding_mode, finding_mode_source in finding_modes:
        rows.extend(
            write_events(
                hook,
                harness,
                event,
                [finding],
                finding_mode,
                finding_mode_source,
                duration_ms,
            )
        )
    return rows


def _renderable_findings(
    finding_modes: list[tuple[Finding, str, str]],
    fallback_findings: list[Finding],
    fallback_mode: str,
) -> tuple[str, list[Finding]]:
    visible = [(finding, mode) for finding, mode, _source in finding_modes if mode != "off"]
    if not visible:
        return "off", []
    if any(mode == "stop" for _finding, mode in visible):
        return "stop", [finding for finding, _mode in visible]
    return "warn", [finding for finding, _mode in visible] or fallback_findings


def _write_findings_file(findings: list[Finding]) -> None:
    path = os.environ.get("CATSTACK_HOOK_FINDINGS_FILE")
    if not path:
        return
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump([finding.rule_id for finding in findings], handle)
    except OSError as exc:
        print(f"catstack-hook-error findings: could not write {path}: {exc}", file=sys.stderr)
