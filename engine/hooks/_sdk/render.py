"""Render hook findings in each harness's native response shape."""
from __future__ import annotations

import json
from collections.abc import Sequence

from engine.hooks._sdk.finding import Finding

BLOCK_EVENTS = {"PreToolUse", "Stop"}


def _message(findings: Sequence[Finding]) -> str:
    return "\n".join(finding.message for finding in findings)


def _json(data: dict) -> str:
    return json.dumps(data) + "\n"


def render_response(
    harness: str,
    hook_event_name: str,
    mode: str,
    findings: Sequence[Finding],
) -> tuple[str, str, int]:
    if mode == "off" or not findings:
        return "", "", 0

    message = _message(findings)
    harness_key = harness.lower()

    if mode == "warn":
        if harness_key == "cursor":
            return _json({"additional_context": message}), "", 0
        return _json({
            "hookSpecificOutput": {
                "hookEventName": hook_event_name,
                "additionalContext": message,
            }
        }), "", 0

    if mode != "stop":
        raise ValueError(f"unknown hook mode {mode!r}")

    if harness_key == "claude":
        if hook_event_name in BLOCK_EVENTS:
            return "", message + "\n", 2
        return _json({
            "decision": "block",
            "reason": message,
            "hookSpecificOutput": {
                "hookEventName": hook_event_name,
                "additionalContext": message,
            },
        }), "", 0

    if harness_key == "cursor":
        return _json({"permission": "deny", "user_message": message}), "", 0

    if harness_key == "codex":
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

    raise ValueError(f"unknown harness {harness!r}")
