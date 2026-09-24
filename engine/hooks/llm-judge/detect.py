from __future__ import annotations

import hashlib
import os
import sys

SDK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk")
if SDK_DIR not in sys.path:
    sys.path.insert(0, SDK_DIR)

from finding import Finding  # noqa: E402

import inbox  # noqa: E402

RULE_HIT = "llm-judge.hit"
RULE_UNCHECKED = "llm-judge.unchecked"


def detect(event: dict[str, object]) -> list[Finding]:
    return _detect_resolved(event, "llm-judge")


def detect_claude_prompt_submit(event: dict[str, object]) -> list[Finding]:
    transcript = event.get("transcript_path")
    if not isinstance(transcript, str) or not transcript:
        print(inbox.NO_TRANSCRIPT.format(harness="Claude UserPromptSubmit"), file=sys.stderr)
        return []
    return _detect_transcript(event, transcript, "Claude UserPromptSubmit")


def detect_claude_post_tool_use(event: dict[str, object]) -> list[Finding]:
    return _detect_resolved(event, "Claude PostToolUse")


def detect_cursor_post_tool_use(event: dict[str, object]) -> list[Finding]:
    return _detect_resolved(event, "Cursor postToolUse")


def detect_codex_post_tool_use(event: dict[str, object]) -> list[Finding]:
    return _detect_resolved(event, "Codex PostToolUse")


def detect_cursor_session(event: dict[str, object]) -> list[Finding]:
    return _detect_resolved(event, "Cursor stop")


def detect_codex_notify(event: dict[str, object]) -> list[Finding]:
    if event.get("type") != "agent-turn-complete":
        return []
    return _detect_resolved(event, "Codex notify")


def _detect_resolved(event: dict[str, object], harness: str) -> list[Finding]:
    transcript = inbox.resolve_transcript(event)
    if not transcript:
        print(inbox.NO_TRANSCRIPT.format(harness=harness), file=sys.stderr)
        return []
    return _detect_transcript(event, transcript, harness)


def _detect_transcript(event: dict[str, object], transcript: str, harness: str) -> list[Finding]:
    try:
        verdicts = inbox.verdicts(transcript)
    except Exception as exc:
        print(f"llm-judge: {harness} could not drain verdicts for {transcript}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return []

    findings: list[Finding] = []
    for item in verdicts:
        text = inbox.message(item)
        if not text:
            continue
        findings.append(_finding(item, transcript, text))
    return _with_legacy_spacing(findings)


def _finding(item: dict, transcript: str, message: str) -> Finding:
    outcome = item.get("outcome")
    rule_id = RULE_HIT if outcome == "hit" else RULE_UNCHECKED
    verdict_id = item.get("id")
    subject = f"{transcript}:{verdict_id}" if isinstance(verdict_id, str) and verdict_id else _message_subject(message)
    hook = item.get("hook")
    reason = item.get("reason")
    evidence = f"hook={hook or 'unknown'} outcome={outcome or 'unknown'} reason={reason or ''}"
    return Finding(rule_id, subject, message, evidence)


def _message_subject(message: str) -> str:
    digest = hashlib.sha256(message.encode("utf-8")).hexdigest()[:16]
    return f"message:{digest}"


def _with_legacy_spacing(findings: list[Finding]) -> list[Finding]:
    if len(findings) < 2:
        return findings
    spaced = []
    for index, finding in enumerate(findings):
        message = finding.message + ("\n" if index < len(findings) - 1 else "")
        spaced.append(Finding(finding.rule_id, finding.subject, message, finding.evidence, finding.output))
    return spaced
