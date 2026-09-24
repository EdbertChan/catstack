from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

from detect import installed_skills, prompt_uses, tool_uses  # noqa: E402
from events import write_stage_event  # noqa: E402

HOOK = "skill-usage-log"
OPT_OUT_ENV = "CATSTACK_SKILL_USAGE_LOG"


def session_id(payload: dict) -> str:
    for key in ("session_id", "sessionId", "conversation_id", "conversationId"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def record(harness: str, kind: str, payload: dict) -> list[tuple[str, str]]:
    if kind == "prompt":
        installed = installed_skills(harness)
        if installed is None:
            print(f"catstack-hook-error {HOOK}: {harness} skill folders unreadable; typed skill commands unchecked", file=sys.stderr)
            write_stage_event(HOOK, harness, session_id(payload), "skill_usage_unchecked", "skills_unreadable")
            return []
        uses = prompt_uses(payload, harness, installed)
    else:
        uses = tool_uses(payload)
    for skill, source in uses:
        write_stage_event(HOOK, harness, session_id(payload), "skill_used", source, fields={"skill": skill})
    return uses


def main(harness: str, kind: str, allow_output: str = "") -> None:
    if os.environ.get(OPT_OUT_ENV) == "0":
        print(allow_output, end="")
        return
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError(f"payload is a JSON {type(payload).__name__}, not an object")
        record(harness, kind, payload)
    except Exception as exc:
        print(f"catstack-hook-error {HOOK}: {type(exc).__name__}: {exc}", file=sys.stderr)
        write_stage_event(HOOK, harness, "", "skill_usage_unchecked", "bad_payload")
    print(allow_output, end="")
