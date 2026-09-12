#!/usr/bin/env python3
"""Submit the reply to diu's five plain-words checkers, in the background.

The phrase files in phrases/ described the rule; nothing ever called them, so
the jargon ban was written five ways and enforced zero times. This is the
caller. Verdicts come back through llm-judge's own inbox on a later prompt, so
nothing here blocks the turn.

Empty text is never submitted. Five verdicts already on disk read
`"transcript": "", "outcome": "clean"` under the directory named for the SHA-1
of the empty string: the judge was handed nothing and reported a pass. A check
that could not run is not a pass, so this refuses to ask rather than collect a
clean answer about no text.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PHRASES_DIR = os.path.join(HERE, "phrases")
JUDGE_DIR = os.path.join(os.path.dirname(HERE), "llm-judge")

CATEGORIES = (
    "plain-words-made-up-labels",
    "plain-words-code-names",
    "plain-words-internal-names",
    "plain-words-tech-jargon",
    "plain-words-status-words",
)


def _judge():
    if JUDGE_DIR not in sys.path:
        sys.path.insert(0, JUDGE_DIR)
    import judge
    return judge


def _phrases():
    if JUDGE_DIR not in sys.path:
        sys.path.insert(0, JUDGE_DIR)
    import phrases
    return phrases


def exchange_text(path: str) -> str:
    """The last user message and the reply after it, as one block."""
    user_parts: list[str] = []
    reply_parts: list[str] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue
            role = data.get("type")
            text = _text_of(data)
            if not text:
                continue
            if role == "user":
                if reply_parts:
                    user_parts, reply_parts = [], []
                user_parts.append(text)
            elif role == "assistant":
                reply_parts.append(text)
    if not reply_parts:
        return ""
    user = "\n".join(user_parts[-1:]).strip()
    reply = "\n".join(reply_parts).strip()
    if not reply:
        return ""
    return f"User said:\n{user}\n\nThe reply:\n{reply}"


def _text_of(entry: dict) -> str:
    message = entry.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    return "\n".join(
        block.get("text", "").strip()
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ).strip()


def enqueue_plain_words(payload: dict) -> list[str]:
    """Job ids submitted, or [] when there was nothing safe to submit."""
    if not isinstance(payload, dict) or payload.get("stop_hook_active"):
        return []
    path = payload.get("transcript_path") or payload.get("transcriptPath") or ""
    if not isinstance(path, str) or not path or not os.path.exists(path):
        return []
    try:
        text = exchange_text(path)
    except OSError as exc:
        sys.stderr.write(f"diu-stop: cannot read transcript {path}: {exc}\n")
        return []
    if not text.strip():
        sys.stderr.write(
            "diu-stop: plain-words not submitted -- the transcript yielded no reply text. "
            "Unchecked, not clean.\n")
        return []

    phrases = _phrases()
    judge = _judge()
    submitted: list[str] = []
    for name in CATEGORIES:
        try:
            dictionary = phrases.load(name, PHRASES_DIR)
            job_id = judge.enqueue(phrases.job(dictionary, path, text))
        except Exception as exc:
            sys.stderr.write(f"diu-stop: plain-words {name} not submitted: {exc!r}\n")
            continue
        if job_id:
            submitted.append(job_id)
    return submitted
