"""Ask the judge's model to say a comment reply again in everyday words, under the cap."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

from judge_channel import llm_judge  # noqa: E402

SWITCH_ENV = "CATSTACK_DIU_COMMENT_REWRITE"
RUNNER_TIMEOUT_SECONDS = 12
PROMPT = (
    "Rewrite this reply to a comment on a document. Keep the outcome and anything the reader must do. "
    "Use short sentences and everyday words, no code names, abbreviations or technical terms, "
    "and stay under {limit} words. Answer with only a JSON object: {{\"reply\": \"<the new reply>\"}}.\n\n"
    "Reply:\n{body}"
)


def rewrite_enabled() -> bool:
    return os.environ.get(SWITCH_ENV, "on") != "off"


def rewrite_reply(body: str, limit: int) -> str | None:
    """The model's shorter, plainer version of the reply, or None when no model answered with usable text."""
    judge, _ = llm_judge()
    result = judge.ask(PROMPT.format(limit=limit, body=body), timeout_seconds=RUNNER_TIMEOUT_SECONDS)
    answer = result.get("answer")
    reply = answer.get("reply") if isinstance(answer, dict) else None
    if isinstance(reply, str) and reply.strip():
        return reply.strip()
    tried = "; ".join(f"{a.get('runner')}: {a.get('reason')}" for a in result.get("attempts") or [])
    print(
        f"catstack-hook-error diu-stop: no usable rewrite of the comment reply ({result.get('outcome')}; {tried or 'no runner tried'}); "
        "posting the original reply with a reminder",
        file=sys.stderr,
    )
    return None
