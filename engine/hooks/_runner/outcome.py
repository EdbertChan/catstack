from __future__ import annotations

import json

OUTCOMES = {
    "timed_out",
    "crashed",
    "blocked",
    "caught_error",
    "spoke",
    "silent",
}


def _stderr_has_hook_error(stderr: bytes) -> bool:
    return any(line.startswith(b"catstack-hook-error ") for line in stderr.splitlines())


def _stdout_blocks(stdout: bytes) -> bool:
    payload = _stdout_json_object(stdout)
    if payload is None:
        return False
    if payload.get("decision") == "block":
        return True
    if payload.get("continue") is False:
        return True
    hook_output = payload.get("hookSpecificOutput")
    if isinstance(hook_output, dict) and hook_output.get("permissionDecision") == "deny":
        return True
    return payload.get("permission") == "deny"


def _stdout_json_object(stdout: bytes) -> dict[str, object] | None:
    try:
        payload = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _has_message_field(payload: dict[str, object]) -> bool:
    message_keys = {
        "additional_context",
        "additionalContext",
        "message",
        "reason",
        "user_message",
    }
    if any(bool(payload.get(key)) for key in message_keys):
        return True
    hook_output = payload.get("hookSpecificOutput")
    if not isinstance(hook_output, dict):
        return False
    return any(bool(hook_output.get(key)) for key in message_keys | {"permissionDecisionReason"})


def _stdout_is_allow_only(stdout: bytes) -> bool:
    payload = _stdout_json_object(stdout)
    if payload is None:
        return False
    return payload.get("continue") is True and not _stdout_blocks(stdout) and not _has_message_field(payload)


def classify(exit_code: int | None, stdout: bytes, stderr: bytes, timed_out: bool) -> str:
    if timed_out:
        return "timed_out"
    if exit_code == 2:
        return "blocked"
    if exit_code not in (0, None):
        return "crashed"
    if _stderr_has_hook_error(stderr):
        return "caught_error"
    if _stdout_blocks(stdout):
        return "blocked"
    if _stdout_is_allow_only(stdout):
        return "silent"
    if stdout.strip():
        return "spoke"
    return "silent"
