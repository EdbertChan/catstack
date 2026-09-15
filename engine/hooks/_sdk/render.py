from __future__ import annotations

import json
from typing import Iterable

from finding import Finding


def _message(findings: Iterable[Finding]) -> str:
    parts = []
    for finding in findings:
        text = finding.message
        if finding.evidence:
            text = f"{text}\nEvidence: {finding.evidence}"
        parts.append(text)
    return "\n\n".join(parts)


def _hook_output(hook_event_name: str, key: str, value: str) -> dict[str, object]:
    return {
        "hookSpecificOutput": {
            "hookEventName": hook_event_name,
            key: value,
        }
    }


def render_response(
    harness: str,
    hook_event_name: str,
    mode: str,
    findings: list[Finding],
) -> tuple[str, str, int]:
    if mode == "off" or not findings:
        return "", "", 0

    message = _message(findings)
    if mode == "warn":
        if harness == "cursor":
            return json.dumps({"additional_context": message}) + "\n", "", 0
        return (
            json.dumps(_hook_output(hook_event_name, "additionalContext", message)) + "\n",
            "",
            0,
        )

    if mode != "stop":
        return "", "", 0

    if harness == "claude":
        if hook_event_name in {"", "Stop", "PreToolUse"}:
            return "", message + "\n", 2
        return (
            json.dumps(
                {
                    "decision": "block",
                    "reason": message,
                    "hookSpecificOutput": {
                        "hookEventName": hook_event_name,
                        "additionalContext": message,
                    },
                }
            )
            + "\n",
            "",
            0,
        )

    if harness == "cursor":
        return json.dumps({"permission": "deny", "user_message": message}) + "\n", "", 0

    if harness == "codex":
        if hook_event_name == "PreToolUse":
            return (
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": hook_event_name,
                            "permissionDecision": "deny",
                            "permissionDecisionReason": message,
                        }
                    }
                )
                + "\n",
                "",
                0,
            )
        return (
            json.dumps(
                {
                    "decision": "block",
                    "reason": message,
                    "hookSpecificOutput": {
                        "hookEventName": hook_event_name,
                        "additionalContext": message,
                    },
                }
            )
            + "\n",
            "",
            0,
        )

    return "", "", 0
