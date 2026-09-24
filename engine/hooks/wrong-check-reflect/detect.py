from __future__ import annotations
import sys

import functools
import hashlib
import importlib.util
import json
import os
import re
import uuid

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_flags"))

from flags import enforcement_gate  # noqa: E402

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
LLM_JUDGE_DIR = os.path.join(os.path.dirname(HOOKS_DIR), "llm-judge")
LLM_JUDGE_PATH = os.path.join(LLM_JUDGE_DIR, "judge.py")
PHRASES_PATH = os.path.join(LLM_JUDGE_DIR, "phrases.py")

STATE_DIR = os.environ.get(
    "WRONG_CHECK_REFLECT_STATE_DIR",
    os.path.join(os.path.expanduser("~"), ".cache", "catstack-wrong-check-reflect"),
)

ALREADY_REFLECT_RE = re.compile(
    r"(?i)<command-name>\s*/?(?:reflect|automate-me)\b"
    r"|<command-message>\s*(?:reflect|automate-me)\s*</command-message>"
)
META_USER_PREFIXES = (
    "<local-command", "<task-notification", "<system", "Stop hook feedback")

FOLLOWUP = (
    "Wrong-check admission on this transcript. This is a FAILURE, "
    "not a preference ping: a claim went out before a real check. Finish the "
    "live correction first. Then read the reflect skill and spawn a subagent "
    "for steps 1-4 on this exact transcript. Present Accepted / Backlog / "
    "Route-to-automate-me / Rejected. Do not skip because the task also finished."
)


def reply_key(transcript_path: str, text: str) -> str:
    """One-shot key for a single reply, not for a whole session.

    Keying on the transcript alone made the hook fire at most once per
    session, and the Stop that spent the key was the Stop of the reply
    BEFORE the correction -- so the correction itself, a minute later, was
    already marked as prompted. A reply is the thing being judged, so the
    reply's text is what the key is made of. The transcript stays in the key
    so the same sentence in two sessions is two chances, not one.
    """
    base = os.path.abspath(transcript_path) if transcript_path else "no-transcript"
    return base + "\n" + hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _state_file(key: str) -> str:
    digest = hashlib.sha1((key or "no-transcript").encode()).hexdigest()[:16]
    return os.path.join(STATE_DIR, f"{digest}.prompted")


def already_prompted(key: str) -> bool:
    return os.path.isfile(_state_file(key or "no-transcript"))


def mark_prompted(key: str) -> None:
    path = _state_file(key or "no-transcript")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write((key or "") + "\n")


def _is_user_line(data: dict) -> bool:
    if data.get("type") == "user":
        return True
    message = data.get("message")
    return isinstance(message, dict) and message.get("role") == "user"


def _is_tool_result_line(data: dict) -> bool:
    """True for a user-shaped row that is only a tool's output.

    Claude Code files every tool result as `type: "user"` and, unlike its
    other injections, marks it with neither `isMeta` nor `isSidechain` -- the
    record it does carry is a `tool_result` content block, plus a
    `toolUseResult` field alongside the message. Reading that is the same
    move `engine/hooks/agent-relay-attribution/detect.py:76` makes.
    """
    if data.get("toolUseResult") is not None:
        return True
    message = data.get("message")
    content = message.get("content") if isinstance(message, dict) else data.get("content")
    return isinstance(content, list) and any(
        isinstance(block, dict) and block.get("type") == "tool_result" for block in content
    )


def _is_meta_line(data: dict) -> bool:
    """True for a user-shaped row that is not the person speaking.

    The harness files its own injections as `type: "user"`: a Stop hook's
    feedback, a skill's body, a subagent's transcript, a tool's result. Each
    carries a record saying so -- `isMeta`, which is what
    `engine/skills/reflect/scripts/token_audit.py:313` keys off, or the
    `tool_result` shape above -- so this reads the record instead of the
    prose. A prose prefix could only ever catch the wordings someone had
    already seen -- and it missed both the hook feedback and the reflect
    skill's own body, which is how running `/reflect` disarmed this hook.

    `META_USER_PREFIXES` lists only harness text filed as a `type: "user"`
    row. A typed slash command does not belong on it:
    `<command-name>/reflect</command-name>` is the person opening a turn, and
    the turn window starts at the person's own last message. Adding a
    `<command` prefix there would read the person's own `/reflect` as harness
    text and re-arm the hook the person just asked to skip.
    """
    if data.get("isMeta") or data.get("agentId") or data.get("isSidechain"):
        return True
    if _is_tool_result_line(data):
        return True
    return _message_text(data).lstrip().startswith(META_USER_PREFIXES)


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


def _user_role(data: dict) -> str:
    """Which kind of user-shaped row this is: "meta", "stacked", or "user".

    Only "user" may anchor a turn. "meta" is the harness talking. "stacked"
    is the person, but not the start of anything: `/reflect /cat-mode text`
    is one submission that the harness writes as an envelope row per
    command, flagging every row after the first `stackedExpansion` -- the
    same field `engine/skills/reflect/scripts/transcript_provenance.py:158`
    reads to keep one submission from counting as several messages. All
    three roles have their text scanned; the role only decides where the
    turn starts.
    """
    if _is_meta_line(data):
        return "meta"
    return "stacked" if data.get("stackedExpansion") else "user"


def _transcript_roles(path: str) -> list[tuple[str, str]] | None:
    """(role, text) per transcript line, or None when the file cannot be read."""
    rows: list[tuple[str, str]] = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(data, dict):
                    continue
                if _is_user_line(data):
                    rows.append((_user_role(data), _message_text(data)))
                elif _is_assistant_line(data):
                    rows.append(("assistant", _message_text(data)))
    except OSError as exc:
        print(
            f"catstack-hook-error wrong-check-reflect: cannot read {path}, "
            f"the user's own reflect request is unchecked: {exc}",
            file=sys.stderr,
        )
        return None
    return rows


def user_already_asked_reflect(path: str) -> bool:
    """True when the user invoked reflect in the turn that produced this reply.

    Only a real invocation counts, which the harness records as a
    `<command-name>/reflect</command-name>` envelope. Prose that merely says
    the word does not: `"Claim I made was wrong" is a trigger for /reflect`
    describes the rule, it does not ask for anything, and suppressing on it
    let a sentence about the hook switch the hook off. Erring toward asking
    is the safe direction for a detector that spoke 0 times in 1,682 runs.

    Scoped to that one turn on purpose. Scanning the whole transcript meant a
    single `/reflect` typed at the start of a session switched the detector
    off for every reply after it, however many hours later.

    The turn is the stretch from the person's own last message to the end of
    the file. Anchoring it on assistant rows instead was wrong twice over. A
    Stop payload carries the reply before its row is written, so the last
    assistant row was then the PREVIOUS turn's reply: that turn's `/reflect`
    suppressed this one -- the session lockout back, just one turn wide --
    and the `/reflect` on the current message sat after the window and was
    ignored. And a turn writes more than one assistant row: mid-turn
    narration and a subagent's sidechain rows each pushed the window's start
    past the message that opened the turn. The person's message is the row
    that actually starts a turn, so it is the anchor; rows after it are this
    turn's whether or not the reply has landed yet.

    A tool result is filed as a `type: "user"` row too, so it only counts as
    the person speaking if nothing checks -- and then the first tool call of
    the turn became the anchor and the `/reflect` that opened the turn fell
    outside the window. `_is_meta_line` rules those rows out.

    One submission can also write more than one of the person's own rows:
    `/reflect /cat-mode text` files an envelope per command, and the later
    ones carry `stackedExpansion`. Those are the same breath, not a new
    turn, so `_user_role` keeps them from anchoring -- otherwise `/cat-mode`
    started the window and the `/reflect` typed beside it sat outside it.
    """
    if not path or not os.path.isfile(path):
        return False
    rows = _transcript_roles(path)
    if rows is None:
        return False
    start = 0
    for index in range(len(rows) - 1, -1, -1):
        if rows[index][0] == "user":
            start = index
            break
    for role, text in rows[start:]:
        if role == "assistant" or not text:
            continue
        if ALREADY_REFLECT_RE.search(text):
            return True
    return False


def resolve_transcript(payload: dict) -> str:
    agent = payload.get("agent_transcript_path")
    if isinstance(agent, str):
        return agent if os.path.isfile(agent) else ""
    direct = payload.get("transcript_path") or payload.get("transcriptPath")
    if isinstance(direct, str) and os.path.isfile(direct):
        return direct
    conv = payload.get("conversation_id") or payload.get("conversationId")
    if isinstance(conv, str) and conv.strip():
        conv = conv.strip()
        root = os.path.join(os.path.expanduser("~"), ".cursor", "projects")
        try:
            for project in os.listdir(root):
                candidate = os.path.join(
                    root, project, "agent-transcripts", conv, f"{conv}.jsonl"
                )
                if os.path.isfile(candidate):
                    return candidate
        except OSError:
            pass
    return ""


def _is_assistant_line(data: dict) -> bool:
    if data.get("type") == "assistant":
        return True
    message = data.get("message")
    return isinstance(message, dict) and message.get("role") == "assistant"


def last_assistant_from_transcript(path: str) -> str:
    if not path or not os.path.isfile(path):
        return ""
    last = ""
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(data, dict) or not _is_assistant_line(data):
                    continue
                text = _message_text(data)
                if text.strip():
                    last = text
    except OSError:
        return ""
    return last


def last_assistant_text(payload: dict, transcript_path: str = "") -> str:
    for key in (
        "last_assistant_message",
        "last-assistant-message",
        "lastAssistantMessage",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return last_assistant_from_transcript(transcript_path)


def decide(payload: dict) -> str | None:
    return None


@functools.cache
def _judge():
    spec = importlib.util.spec_from_file_location("llm_judge", LLM_JUDGE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load llm-judge from {LLM_JUDGE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@functools.cache
def _phrases():
    spec = importlib.util.spec_from_file_location("llm_judge_phrases", PHRASES_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load llm-judge phrases from {PHRASES_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def enqueue_judge(payload: dict) -> str | None:
    if not isinstance(payload, dict) or payload.get("stop_hook_active"):
        return None
    if not enforcement_gate("wrong-check-reflect", payload.get("cwd")):
        return None
    path = resolve_transcript(payload)
    text = last_assistant_text(payload, path)
    key = reply_key(path, text)
    if not text.strip() or already_prompted(key):
        return None
    if path and user_already_asked_reflect(path):
        return None
    dictionary = _phrases().load("wrong-check-reflect")
    job = _phrases().job(dictionary, path, text)
    job["id"] = uuid.uuid4().hex
    job_id = _judge().enqueue(job)
    if job_id is not None:
        mark_prompted(key)
    return job_id


def try_enqueue_judge(payload: dict) -> None:
    try:
        enqueue_judge(payload)
    except Exception as exc:
        print(f"catstack-hook-error wrong-check-reflect: {type(exc).__name__}: {exc}", file=sys.stderr)
        return
