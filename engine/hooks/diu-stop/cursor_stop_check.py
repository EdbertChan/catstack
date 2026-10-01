#!/usr/bin/env python3
"""Cursor stop hook entrypoint for diu-stop."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from claude_stop_check import detect as detect_diu_stop  # noqa: E402
from finding import Finding  # noqa: E402
from runtime import run_hook  # noqa: E402

RULE_MISSING_REPLY = "diu-stop.missing-reply"
_PAYLOAD_TEXT_KEYS = (
    "last_assistant_message",
    "lastAssistantMessage",
    "last-assistant-message",
    "assistant_message",
    "response",
)


def _payload_text(event):
    for key in _PAYLOAD_TEXT_KEYS:
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _blocks_text(message):
    """Text blocks on one assistant row.

    A Cursor transcript stores role on the row. The reply itself is
    message.content, a list of typed blocks. Tool calls are not the reply.
    """
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
            if block["text"].strip():
                parts.append(block["text"])
    return "\n".join(parts).strip()


def _last_assistant_text(path):
    """Last assistant prose in a Cursor jsonl, or ("", reason) when it cannot be loaded.

    Role lives on the row, not under message. A row with no text does not
    count: the previous assistant prose is still the last reply.
    """
    last = ""
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict) or entry.get("role") != "assistant":
                    continue
                text = _blocks_text(entry.get("message"))
                if text:
                    last = text
    except (OSError, UnicodeError):
        return "", "the transcript could not be read"
    if not last:
        return "", "the transcript had no assistant text"
    return last, None


def _transcript_path(event):
    for key in ("transcript_path", "transcriptPath"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _missing_reply(reason):
    message = (
        "No assistant reply was available to check "
        f"({reason}). This turn is not a short reply."
    )
    return Finding(
        rule_id=RULE_MISSING_REPLY,
        subject=reason,
        message=message,
        evidence=message,
    )


def detect(event):
    if not isinstance(event, dict):
        return detect_diu_stop({})
    if event.get("agent_id"):
        return detect_diu_stop(event)
    text = _payload_text(event)
    if text is None:
        path = _transcript_path(event)
        if path is None:
            return [_missing_reply("the stop payload had no reply and no transcript path")]
        text, reason = _last_assistant_text(path)
        if reason:
            return [_missing_reply(reason)]
    enriched = dict(event)
    enriched["last_assistant_message"] = text
    return detect_diu_stop(enriched)


def main():
    run_hook("diu-stop", "cursor", detect, "stop")


if __name__ == "__main__":
    main()
