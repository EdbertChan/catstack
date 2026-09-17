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
        return "", "", 0

    message = _message(findings)
    if harness == "claude":
        return _render_claude(hook_event_name, mode, message)
    if harness == "cursor":
        return _render_cursor(mode, message)
    if harness == "codex":
        return _render_codex(hook_event_name, mode, message)
    raise ValueError(f"unknown hook harness {harness!r}")


def _render_claude(hook_event_name: str, mode: str, message: str) -> tuple[str, str, int]:
    if mode == "stop" and hook_event_name in {"Stop", "PreToolUse"}:
        return "", message + "\n", 2
    return _json({
        "hookSpecificOutput": {
            "hookEventName": hook_event_name,
            "additionalContext": message,
        }
    }), "", 0


def _render_cursor(mode: str, message: str) -> tuple[str, str, int]:
    if mode == "stop":
        return _json({"continue": False, "permission": "deny", "user_message": message}), "", 0
    return _json({"additional_context": message}), "", 0


def _render_codex(hook_event_name: str, mode: str, message: str) -> tuple[str, str, int]:
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


def _json(value: dict[str, object]) -> str:
    return json.dumps(value) + "\n"
