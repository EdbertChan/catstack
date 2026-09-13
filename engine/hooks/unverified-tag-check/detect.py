from __future__ import annotations

import functools
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
import uuid

HOOK_NAME = "unverified-tag-check"
HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
LLM_JUDGE_PATH = os.path.join(os.path.dirname(HOOKS_DIR), "llm-judge", "judge.py")
MARKERS_DIR = os.path.join(os.path.dirname(HOOKS_DIR), "_markers")
STATE_ENV = "CATSTACK_UNVERIFIED_TAG_CHECK_STATE_DIR"
STATE_TTL_SECONDS = 7200
PROMPT_LIMIT = 8000

sys.path.insert(0, MARKERS_DIR)

import markers

REASON_SPLIT_RE = re.compile(r"cannot\s+verify\s*:", re.IGNORECASE)
TAG_BODY_RE = re.compile(r"^\{\{\s*CAT-UNVERIFIED\b(?P<body>[^}]*)\}\}$", re.IGNORECASE | re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")


def _stderr(message: str) -> None:
    print(message, file=sys.stderr)


def _blank_span(chars: list[str], start: int, end: int) -> None:
    for index in range(start, end):
        if chars[index] != "\n":
            chars[index] = " "


def strip_code(text: str) -> str:
    chars = list(text)
    index = 0
    while True:
        start = text.find("```", index)
        if start < 0:
            break
        end = text.find("```", start + 3)
        if end < 0:
            break
        _blank_span(chars, start, end + 3)
        index = end + 3
    fenced = "".join(chars)
    for match in INLINE_CODE_RE.finditer(fenced):
        _blank_span(chars, match.start(), match.end())
    return "".join(chars)


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


def _is_assistant_line(data: dict) -> bool:
    if data.get("type") == "assistant":
        return True
    message = data.get("message")
    return isinstance(message, dict) and message.get("role") == "assistant"


def _last_assistant_from_transcript(path: str) -> str:
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


def resolve_transcript(payload: dict) -> str:
    agent = payload.get("agent_transcript_path")
    if isinstance(agent, str):
        return agent if os.path.isfile(agent) else ""
    direct = payload.get("transcript_path") or payload.get("transcriptPath")
    if isinstance(direct, str) and os.path.isfile(direct):
        return direct
    return ""


def reply_text(payload: dict) -> str:
    value = payload.get("last_assistant_message")
    if isinstance(value, str) and value.strip():
        return value
    return _last_assistant_from_transcript(str(payload.get("transcript_path") or ""))


def _tag_body(tag: str) -> str:
    match = TAG_BODY_RE.match(tag)
    if not match:
        return ""
    body = match.group("body").strip()
    if body.startswith(":"):
        body = body[1:]
    return body.strip()


def tags(text: str) -> list[dict]:
    out = []
    for tag in markers.well_formed_tags(strip_code(text)):
        body = _tag_body(tag)
        parts = REASON_SPLIT_RE.split(body, 1)
        if len(parts) != 2:
            continue
        claim = parts[0].strip(" -:\t\r\n")
        blocker = parts[1].strip(" -:\t\r\n")
        out.append({"claim": claim, "blocker": blocker, "tag": tag})
        if len(out) == 3:
            break
    return out


def normalize_claim(claim: str) -> str:
    return re.sub(r"\W+", " ", claim.lower()).strip()


def state_root() -> str:
    return os.environ.get(STATE_ENV) or os.path.join(os.path.expanduser("~"), ".cache", "catstack-unverified-tag-check")


def state_path(transcript: str) -> str:
    digest = hashlib.sha1(transcript.encode("utf-8")).hexdigest()[:16]
    return os.path.join(state_root(), f"{digest}.json")


def read_state(transcript: str, now: float | None = None) -> dict[str, float]:
    now = time.time() if now is None else now
    path = state_path(transcript)
    try:
        with open(path, encoding="utf-8") as handle:
            loaded = json.load(handle)
    except (OSError, ValueError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    out: dict[str, float] = {}
    for claim, seen_at in loaded.items():
        if not isinstance(claim, str) or isinstance(seen_at, bool) or not isinstance(seen_at, (int, float)):
            return {}
        if seen_at > now:
            continue
        if now - float(seen_at) <= STATE_TTL_SECONDS:
            out[claim] = float(seen_at)
    return out


def write_state(transcript: str, state: dict[str, float]) -> None:
    path = state_path(transcript)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(state, handle, sort_keys=True)
    except Exception as exc:
        print(f"unverified-tag-check: state not written: {type(exc).__name__}: {exc}", file=sys.stderr)


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _paragraph_holding_tag(text: str, tag: str) -> str:
    paragraphs = re.split(r"\n\s*\n", text)
    for paragraph in paragraphs:
        if tag in strip_code(paragraph):
            return paragraph
    for paragraph in paragraphs:
        if "CAT-UNVERIFIED" in paragraph and REASON_SPLIT_RE.search(paragraph):
            return paragraph
    return text


def _prompt(payload: dict, tag: dict) -> str:
    text = reply_text(payload)
    transcript = resolve_transcript(payload)
    cwd = payload.get("cwd") or ""
    paragraph = _clip(_paragraph_holding_tag(text, str(tag.get("tag") or "")), 2000)
    claim = _clip(str(tag.get("claim") or ""), 1500)
    blocker = _clip(str(tag.get("blocker") or ""), 1500)
    prompt = (
        "You check one excuse an AI agent gave for not verifying a claim. You may only read. "
        f"Claim: {claim}. Stated blocker: {blocker}. The reply paragraph: {paragraph}. "
        f"The agent's transcript (JSONL) is at {transcript}; its working folder was {cwd}. "
        "First decide whether the blocker was real: look for a file, log, transcript line, or earlier tool result on this machine that the agent could have used to check the claim, or that shows the 'impossible' thing already worked. "
        "Then decide whether the claim itself is true, false, or unknown from what you can read. "
        "Quote evidence as file:line or a short exact quote; with no evidence, say unknown. "
        "Answer with exactly one JSON object on the last line:\n"
        "{\"blocker_false\": true|false, \"claim_status\": \"true\"|\"false\"|\"unknown\", \"report\": \"<one plain sentence: whether the blocker held, what the claim turned out to be, and the evidence>\"}"
    )
    return prompt[:PROMPT_LIMIT]


def build_job(payload: dict, tag: dict) -> dict:
    claim = str(tag.get("claim") or "")
    return {
        "id": uuid.uuid4().hex,
        "hook": HOOK_NAME,
        "transcript": resolve_transcript(payload),
        "mode": "investigate",
        "timeout_seconds": 300,
        "cwd": payload.get("cwd") or "",
        "hit_if_all_true": [],
        "on_hit": f"unverified-tag-check: checked \"{_clip(claim, 120)}\". Tell the user this result in plain words:",
        "prompt": _prompt(payload, tag),
    }


@functools.cache
def _judge():
    spec = importlib.util.spec_from_file_location("llm_judge", LLM_JUDGE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load llm-judge from {LLM_JUDGE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_reply(payload: dict) -> list[str]:
    if not isinstance(payload, dict):
        return []
    transcript = resolve_transcript(payload)
    if not transcript:
        _stderr("unverified-tag-check: no transcript, reply not checked")
        return []
    text = reply_text(payload)
    if not text.strip():
        return []
    now = time.time()
    state = read_state(transcript, now=now)
    seen = set(state)
    ids = []
    for tag in tags(text):
        normalized = normalize_claim(str(tag.get("claim") or ""))
        if not normalized or normalized in seen:
            continue
        job_id = _judge().enqueue(build_job(payload, tag))
        if job_id is not None:
            ids.append(job_id)
            state[normalized] = now
            seen.add(normalized)
    if ids:
        write_state(transcript, state)
    return ids


def try_check_reply(payload: dict) -> None:
    try:
        check_reply(payload)
    except Exception as exc:
        print(f"catstack-hook-error {HOOK_NAME}: {type(exc).__name__}: {exc}", file=sys.stderr)
