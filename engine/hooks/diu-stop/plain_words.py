"""Ask the background judge whether the last reply used wording the user has
to ask about, and wait for the answer.

The word lists live in phrases/, one file per kind of wording. They become one
question, so one model call covers every kind and names the one it found. The
Stop hook waits for that answer and shows it in the same turn, because a
verdict that waits for the user's next message is a verdict the user may never
see. When no answer arrives in time, the turn ends unblocked.
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid

HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
LLM_JUDGE_DIR = os.path.join(os.path.dirname(HOOK_DIR), "llm-judge")
PHRASES_DIR = os.path.join(HOOK_DIR, "phrases")
PREFIX = "plain-words-"
WAIT_ENV = "DIU_PLAIN_WORDS_WAIT_SECONDS"
DEFAULT_WAIT_SECONDS = 40.0
POLL_SECONDS = 0.5
HOOK_NAME = "diu-plain-words"
TEXT_LIMIT = 4000
META_USER_PREFIXES = ("<command-", "<task-notification", "<system", "<local-command", "Stop hook feedback")
ANSWER_SHAPE = '{"match": true|false, "category": "<list name or empty>", "closest": "<the assistant words, or empty>"}'
MESSAGE = (
    "diu: the last reply used wording the user has had to ask about ({category}): \"{closest}\". "
    "Say it in everyday words, or explain the term in the same sentence."
)


def _llm_judge():
    if LLM_JUDGE_DIR not in sys.path:
        sys.path.insert(0, LLM_JUDGE_DIR)
    import judge
    import phrases

    return judge, phrases


def list_names(directory: str = PHRASES_DIR) -> list[str]:
    try:
        names = os.listdir(directory)
    except OSError as exc:
        raise ValueError(f"{directory}: word lists could not be listed: {exc}") from exc
    return sorted(name[: -len(".json")] for name in names if name.startswith(PREFIX) and name.endswith(".json"))


def _is_user_line(data: dict) -> bool:
    if data.get("type") == "user":
        return True
    message = data.get("message")
    return isinstance(message, dict) and message.get("role") == "user"


def _message_text(data: dict) -> str:
    message = data.get("message")
    content = message.get("content") if isinstance(message, dict) else data.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text") or "")
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return ""


def last_user_message(path: str) -> str:
    if not path or not os.path.isfile(path):
        return ""
    found = ""
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if not isinstance(data, dict) or data.get("isSidechain") or data.get("isMeta"):
                continue
            if not _is_user_line(data):
                continue
            text = _message_text(data).strip()
            if text and not text.startswith(META_USER_PREFIXES):
                found = text
    return found


def prompt(dictionaries: list[dict], asked: str, reply: str) -> str:
    lines = [
        f"Return exactly one line of JSON: {ANSWER_SHAPE}",
        "Each list below names a kind of wording to avoid when writing to this user.",
    ]
    for dictionary in dictionaries:
        lines.append("")
        lines.append(f"List {dictionary['checker']}: {dictionary['meaning']}")
        lines.append(f"Examples that match: {json.dumps(dictionary['match'], ensure_ascii=False)}")
        lines.append(f"Examples that do not match: {json.dumps(dictionary['not_match'], ensure_ascii=False)}")
    lines.extend(
        [
            "",
            "Set match to true only when the ASSISTANT text below uses such wording.",
            "closest must be copied word for word from the ASSISTANT text, never from the lists.",
            "A word the USER used first does not count. A word that is only quoted, negated, or described does not count.",
            "",
            f"USER:\n{asked[-TEXT_LIMIT:]}",
            "",
            f"ASSISTANT:\n{reply[-TEXT_LIMIT:]}",
        ]
    )
    return "\n".join(lines)


def job(payload: dict) -> dict | None:
    reply = payload.get("last_assistant_message") or ""
    transcript = payload.get("transcript_path") or ""
    if not reply.strip() or not transcript or not os.path.isfile(transcript):
        return None
    _, phrases = _llm_judge()
    dictionaries = [phrases.load(name, directory=PHRASES_DIR) for name in list_names()]
    if not dictionaries:
        return None
    return {
        "id": uuid.uuid4().hex,
        "hook": HOOK_NAME,
        "transcript": transcript,
        "prompt": prompt(dictionaries, last_user_message(transcript), reply),
        "hit_if_all_true": ["match"],
        "on_hit": "diu: the last reply used wording the user has had to ask about; say it in everyday words.",
    }


def message_for(verdict: dict, reply: str) -> str:
    if verdict.get("outcome") != "hit":
        return ""
    answer = verdict.get("answer") or {}
    closest = str(answer.get("closest") or "").strip()
    if not closest or closest not in reply:
        return ""
    return MESSAGE.format(category=str(answer.get("category") or "unnamed list"), closest=closest)


def wait_seconds() -> float:
    raw = os.environ.get(WAIT_ENV)
    if raw is None:
        return DEFAULT_WAIT_SECONDS
    try:
        return max(0.0, float(raw))
    except ValueError:
        return DEFAULT_WAIT_SECONDS


def check_reply(payload: dict) -> str:
    if not isinstance(payload, dict) or payload.get("agent_id") or payload.get("stop_hook_active"):
        return ""
    built = job(payload)
    if built is None:
        return ""
    judge, _ = _llm_judge()
    if judge.enqueue(built) is None:
        return ""
    deadline = time.monotonic() + wait_seconds()
    transcript = built["transcript"]
    while time.monotonic() < deadline:
        for verdict in judge.drain(transcript):
            if verdict.get("id") == built["id"]:
                return message_for(verdict, payload.get("last_assistant_message") or "")
        time.sleep(POLL_SECONDS)
    return ""


def try_check_reply(payload: dict) -> str:
    """check_reply for the hook scripts: an error is logged, never raised."""
    try:
        return check_reply(payload)
    except Exception as exc:
        sys.stderr.write(f"diu-stop: plain-words check failed: {type(exc).__name__}: {exc}\n")
        return ""
