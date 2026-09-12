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
    try:
        payload = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    if payload.get("decision") == "block":
        return True
    if payload.get("continue") is False:
        return True
    hook_output = payload.get("hookSpecificOutput")
    if isinstance(hook_output, dict) and hook_output.get("permissionDecision") == "deny":
        return True
    return payload.get("permission") == "deny"


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
    if stdout.strip():
        return "spoke"
    return "silent"
