from __future__ import annotations

import json
import os
import sys
import time
import traceback
from collections.abc import Callable
from typing import NoReturn

import followup
from events import write_events
from finding import STEP_LOG_FIELDS, Finding
from modes import effective_finding_modes, finding_enforcement
from transcripts import is_publishable_model
from render import render


def run_hook(
    hook: str,
    harness: str,
    detect: Callable[[dict[str, object]], list[Finding]],
    hook_event_name: str | None = None,
    inspect_raw_payload: bool = False,
    json_error_stderr: bool = True,
    json_error_stderr_prefix: str | None = None,
    silent_output: dict[str, object] | None = None,
    legacy_fail_open_context: str | None = None,
    unchecked_fails_open: bool = False,
) -> NoReturn:
    """Run one hook: read the payload, call ``detect``, log, render, exit.

    ``unchecked_fails_open`` is the hook's written-down answer to "what happens
    when this check could not run". Off (the default), a finding whose rule id
    ends in ``.unchecked`` is an ordinary finding: it blocks or warns per the
    hook's mode, which is how a fail-closed gate such as categorical-scope-guard
    or external-claim-gate refuses a command it could not read. On, such a
    finding is taken out of the blocking set and written to the metrics log as
    an ``unchecked`` row instead, so a reply checker that could not load its
    grader stays quiet and still leaves a trace. A detector that wants the
    second behaviour for one finding only can append it to
    ``event["_catstack_unchecked_findings"]`` itself.

    A detector with rows to log that are not the hook's decision -- a
    measurement per playbook step beside one block for the whole turn -- appends
    them to ``event["_catstack_silent_findings"]``. Those are written as
    ``silent`` rows and never rendered, so a hook whose mode is ``stop`` blocks
    on what it returns and stays quiet about what it merely recorded.
    """
    started = time.monotonic()
    raw = sys.stdin.read()
    try:
        event = json.loads(raw)
    except json.JSONDecodeError as exc:
        if not inspect_raw_payload:
            _write_findings_file([])
            if json_error_stderr_prefix is not None:
                print(f"{json_error_stderr_prefix}: {type(exc).__name__}: {exc}", file=sys.stderr)
            elif json_error_stderr:
                print(f"catstack-hook-error {hook}: JSONDecodeError: hook payload is not JSON: {exc}", file=sys.stderr)
            _legacy_fail_open(hook, legacy_fail_open_context)
            stdout_text, _stderr_text, _exit_code = render(
                harness,
                hook_event_name or "",
                "warn",
                [],
                silent_output=silent_output,
            )
            if stdout_text:
                sys.stdout.write(stdout_text)
            sys.exit(0)
        event = {
            "_raw_payload": raw,
            "_payload_error": f"the hook payload is not JSON ({exc})",
            "_payload_error_type": type(exc).__name__,
            "_payload_error_detail": str(exc),
        }
    if not isinstance(event, dict):
        event = (
            {
                "_raw_payload": raw,
                "_payload_error": "the hook payload is not a JSON object",
            }
            if inspect_raw_payload
            else {}
        )
    else:
        event.setdefault("_raw_payload", raw)
    event.setdefault("_catstack_harness", harness)
    _apply_test_model_fixture(event)
    if hook_event_name and not _hook_event_name(event):
        event["hook_event_name"] = hook_event_name

    hook_event_name = _hook_event_name(event)
    try:
        findings = detect(event)
        if unchecked_fails_open:
            findings = _route_unchecked(event, findings)
    except Exception as exc:
        duration_ms = _duration_ms(started)
        _write_findings_file([])
        print(f"catstack-hook-error {hook}: {type(exc).__name__}: {exc}", file=sys.stderr)
        _legacy_fail_open(hook, legacy_fail_open_context)
        write_events(hook, harness, event, [], "off", "runtime", duration_ms, action="crashed")
        sys.exit(0)

    _write_detector_stderr(event)
    duration_ms = _duration_ms(started)
    mode, mode_source, finding_modes = effective_finding_modes(hook, event, findings)
    _write_findings_file(findings + _unchecked_findings(event) + _silent_findings(event))
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
    level, downgrade_reason = _enforcement(hook, harness, event)
    event_rows = _write_event_rows(
        hook,
        harness,
        event,
        findings,
        finding_modes,
        mode,
        mode_source,
        duration_ms,
        level,
        downgrade_reason,
    )
    if event_rows:
        followup.update_followups(hook, harness, event, event_rows, mode, mode_source, sys.stderr)
    rendered_mode, rendered_findings = _renderable_findings(finding_modes, findings, mode)
    stdout_text, stderr_text, exit_code = render(
        harness, hook_event_name, rendered_mode, rendered_findings, silent_output=silent_output
    )
    if stdout_text:
        sys.stdout.write(stdout_text)
    if stderr_text:
        sys.stderr.write(stderr_text)
    sys.exit(exit_code)


UNCHECKED_RULE_SUFFIX = ".unchecked"
UNCHECKED_CHANNEL = "_catstack_unchecked_findings"
SILENT_CHANNEL = "_catstack_silent_findings"


def _route_unchecked(event: dict[str, object], findings: list[Finding]) -> list[Finding]:
    kept: list[Finding] = []
    for finding in findings:
        if finding.rule_id.endswith(UNCHECKED_RULE_SUFFIX):
            channel = event.get(UNCHECKED_CHANNEL)
            if not isinstance(channel, list):
                channel = []
                event[UNCHECKED_CHANNEL] = channel
            channel.append(finding)
        else:
            kept.append(finding)
    return kept


def _hook_event_name(event: dict[str, object]) -> str:
    for key in ("hook_event_name", "hookEventName", "event"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _apply_test_model_fixture(event: dict[str, object]) -> None:
    model = os.environ.get("CATSTACK_HOOK_TEST_MODEL")
    if not is_publishable_model(model):
        return
    for key in ("model", "model_id", "modelId", "agent_model"):
        if key in event:
            return
    metadata = event.get("metadata")
    if isinstance(metadata, dict) and any(key in metadata for key in ("model", "model_id", "modelId")):
        return
    event["model"] = model.strip()


def _duration_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _enforcement(hook: str, harness: str, event: dict[str, object]) -> tuple[str, str]:
    """The enforcement level this hook's rules reach on the running harness, and any downgrade reason.

    A registry that cannot be read here leaves the level unknown rather than
    clean: the level is empty and the reason says the policy could not be read.
    """
    try:
        return finding_enforcement(hook, harness, event)
    except Exception as exc:
        print(f"catstack-hook-error {hook}: enforcement policy unread: {type(exc).__name__}: {exc}", file=sys.stderr)
        return "", f"enforcement policy unread: {type(exc).__name__}: {exc}"


def _write_event_rows(
    hook: str,
    harness: str,
    event: dict[str, object],
    findings: list[Finding],
    finding_modes: list[tuple[Finding, str, str]],
    mode: str,
    mode_source: str,
    duration_ms: int,
    level: str = "",
    downgrade_reason: str = "",
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for finding in _unchecked_findings(event):
        rows.extend(
            write_events(
                hook,
                harness,
                event,
                [finding],
                mode,
                mode_source,
                duration_ms,
                action="unchecked",
                effective_level=level,
                downgrade_reason=downgrade_reason,
            )
        )
    for finding in _silent_findings(event):
        rows.extend(
            write_events(
                hook,
                harness,
                event,
                [finding],
                mode,
                mode_source,
                duration_ms,
                action="silent",
                effective_level=level,
                downgrade_reason=downgrade_reason,
            )
        )
    if not findings:
        if rows:
            return rows
        return write_events(
            hook,
            harness,
            event,
            [],
            mode,
            mode_source,
            duration_ms,
            effective_level=level,
            downgrade_reason=downgrade_reason,
        )
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
                effective_level=level,
                downgrade_reason=downgrade_reason,
            )
        )
    return rows


def _unchecked_findings(event: dict[str, object]) -> list[Finding]:
    return _channel_findings(event, UNCHECKED_CHANNEL)


def _silent_findings(event: dict[str, object]) -> list[Finding]:
    """Rows a detector asked to have logged without rendering them."""
    return _channel_findings(event, SILENT_CHANNEL)


def _channel_findings(event: dict[str, object], name: str) -> list[Finding]:
    raw = event.get(name)
    if not isinstance(raw, list):
        return []
    return [finding for finding in raw if isinstance(finding, Finding)]


def _renderable_findings(
    finding_modes: list[tuple[Finding, str, str]],
    fallback_findings: list[Finding],
    fallback_mode: str,
) -> tuple[str, list[Finding]]:
    visible = [(finding, mode) for finding, mode, _source in finding_modes if mode != "off"]
    if not visible:
        if not fallback_findings:
            return fallback_mode, []
        return "off", []
    if any(mode == "stop" for _finding, mode in visible):
        return "stop", [finding for finding, _mode in visible]
    return "warn", [finding for finding, _mode in visible] or fallback_findings


def _findings_file_entry(finding: Finding) -> str | dict[str, str]:
    """One findings file entry: the rule id alone, or an object when the finding carries a step log."""
    step_log = {name: getattr(finding, name) for name in STEP_LOG_FIELDS if getattr(finding, name)}
    if not step_log:
        return finding.rule_id
    return {"rule_id": finding.rule_id, **step_log}


def _write_findings_file(findings: list[Finding]) -> None:
    path = os.environ.get("CATSTACK_HOOK_FINDINGS_FILE")
    if not path:
        return
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump([_findings_file_entry(finding) for finding in findings], handle)
    except OSError as exc:
        print(f"catstack-hook-error findings: could not write {path}: {exc}", file=sys.stderr)


def _write_detector_stderr(event: dict[str, object]) -> None:
    raw = event.get("_catstack_stderr_lines")
    if not isinstance(raw, list):
        return
    for line in raw:
        if isinstance(line, str) and line:
            print(line, file=sys.stderr)


def _legacy_fail_open(hook: str, context: str | None) -> None:
    if not context:
        return
    print(f"{hook} {context}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
