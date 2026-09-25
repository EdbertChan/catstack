from __future__ import annotations

import json
from typing import Sequence

from finding import Finding


def render(
    harness: str,
    hook_event_name: str,
    mode: str,
    findings: Sequence[Finding],
) -> tuple[str, str, int]:
    if mode == "off":
        return "", "", 0
    if not findings:
        if harness == "cursor" and hook_event_name == "beforeSubmitPrompt":
            return _json({"continue": True}), "", 0
        if harness == "cursor" and hook_event_name == "stop":
            return _json({}), "", 0
        return "", "", 0

    message = _message(findings)
    if harness == "claude":
        return _render_claude(hook_event_name, mode, message, findings)
    if harness == "cursor":
        return _render_cursor(hook_event_name, mode, message)
    if harness == "codex":
        return _render_codex(hook_event_name, mode, message)
    raise ValueError(f"unknown hook harness {harness!r}")


def _render_claude(
    hook_event_name: str,
    mode: str,
    message: str,
    findings: Sequence[Finding],
) -> tuple[str, str, int]:
    if mode == "stop" and hook_event_name in {"Stop", "SubagentStop", "PreToolUse"}:
        return "", message + "\n", 2
    updated_input = _updated_input(findings)
    if hook_event_name == "PreToolUse" and updated_input is not None:
        return _json(_with_system_message({
            "hookSpecificOutput": {
                "hookEventName": hook_event_name,
                "updatedInput": updated_input,
            }
        }, findings)), "", 0
    return _json(_with_system_message({
        "hookSpecificOutput": {
            "hookEventName": hook_event_name,
            "additionalContext": message,
        }
    }, findings)), "", 0


def _render_cursor(hook_event_name: str, mode: str, message: str) -> tuple[str, str, int]:
    if hook_event_name == "stop" and mode != "stop":
        return _json({"followup_message": message}), "", 0
    if mode == "stop":
        return _json({"continue": False, "permission": "deny", "user_message": message}), "", 0
    return _json({"additional_context": message}), "", 0


def _render_codex(hook_event_name: str, mode: str, message: str) -> tuple[str, str, int]:
    if hook_event_name == "Notify":
        return "", message + "\n", 0
    if mode == "stop":
        if hook_event_name == "PreToolUse":
            return _json({
                "hookSpecificOutput": {
                    "hookEventName": hook_event_name,
                    "permissionDecision": "deny",
                    "permissionDecisionReason": message,
                }
            }), "", 0
        return _json({
            "decision": "block",
            "reason": message,
            "hookSpecificOutput": {
                "hookEventName": hook_event_name,
                "additionalContext": message,
            },
        }), "", 0
    return _json({
        "hookSpecificOutput": {
            "hookEventName": hook_event_name,
            "additionalContext": message,
        }
    }), "", 0


def _message(findings: Sequence[Finding]) -> str:
    return "\n".join(finding.message for finding in findings)


def _updated_input(findings: Sequence[Finding]) -> dict[str, object] | None:
    for finding in findings:
        output = finding.output
        if isinstance(output, dict) and isinstance(output.get("updatedInput"), dict):
            return output["updatedInput"]
    return None


def _with_system_message(body: dict[str, object], findings: Sequence[Finding]) -> dict[str, object]:
    for finding in findings:
        output = finding.output
        if isinstance(output, dict) and isinstance(output.get("systemMessage"), str):
            body["systemMessage"] = output["systemMessage"]
            break
    return body


def _json(value: dict[str, object]) -> str:
    return json.dumps(value) + "\n"
