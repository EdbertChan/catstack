from __future__ import annotations

import os
import sys

SDK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk")
if SDK_DIR not in sys.path:
    sys.path.insert(0, SDK_DIR)

from finding import Finding  # noqa: E402

import inbox  # noqa: E402


def detect(event: dict[str, object]) -> list[Finding]:
    if _is_irrelevant_codex_notify(event):
        return []
    transcript = _transcript(event)
    if not transcript:
        _stderr(event, inbox.NO_TRANSCRIPT.format(harness=_harness_label(event)))
        return []
    delivered, unchecked = inbox.findings(transcript)
    notice = inbox.user_notice(unchecked)
    if notice:
        delivered = [
            Finding(
                finding.rule_id,
                finding.subject,
                finding.message,
                finding.evidence,
                output={"systemMessage": notice},
            )
            for finding in delivered
        ]
    return _with_paragraph_spacing(delivered)


def _transcript(event: dict[str, object]) -> str:
    if _harness_label(event) == "Claude UserPromptSubmit":
        transcript = event.get("transcript_path")
        return transcript if isinstance(transcript, str) and transcript else ""
    return inbox.resolve_transcript(event)


def _is_irrelevant_codex_notify(event: dict[str, object]) -> bool:
    return _hook_event_name(event) == "Notify" and event.get("type") != "agent-turn-complete"


def _hook_event_name(event: dict[str, object]) -> str:
    for key in ("hook_event_name", "hookEventName", "event"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _harness_label(event: dict[str, object]) -> str:
    harness = event.get("_catstack_harness")
    hook_event_name = _hook_event_name(event)
    if harness == "claude" and hook_event_name == "UserPromptSubmit":
        return "Claude UserPromptSubmit"
    if harness == "claude" and hook_event_name == "PostToolUse":
        return "Claude PostToolUse"
    if harness == "codex" and hook_event_name == "Notify":
        return "Codex notify"
    if harness == "codex" and hook_event_name == "PostToolUse":
        return "Codex PostToolUse"
    if harness == "cursor" and hook_event_name == "stop":
        return "Cursor stop"
    if harness == "cursor" and hook_event_name == "postToolUse":
        return "Cursor postToolUse"
    return str(harness or "unknown harness")


def _stderr(event: dict[str, object], line: str) -> None:
    lines = event.setdefault("_catstack_stderr_lines", [])
    if isinstance(lines, list):
        lines.append(line)


def _with_paragraph_spacing(findings: list[Finding]) -> list[Finding]:
    if len(findings) < 2:
        return findings
    spaced = []
    for index, finding in enumerate(findings):
        message = finding.message + ("\n" if index < len(findings) - 1 else "")
        spaced.append(
            Finding(
                finding.rule_id,
                finding.subject,
                message,
                finding.evidence,
                finding.output,
            )
        )
    return spaced
