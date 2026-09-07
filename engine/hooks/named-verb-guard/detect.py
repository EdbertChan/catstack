"""named-verb-guard: the user named a verb; the reply must show that verb happened.

Two triggers, both read from the user's last human message:

1. Named verb. An imperative repro / reproduce / test / run / rerun /
   regenerate / prove / show / delete / revert, or a short message that
   opens with "stop". Each verb maps to an evidence class the reply (or the
   turn's tool calls) must carry.
2. Proof polling. The second or later "prove it" / "show me" / "are you
   sure" / "did you actually run it" in one session. The reply must then
   carry a command-and-output block, a file:line, a URL, or `UNVERIFIED:`.

Evidence is shape only: a closed fenced block, a `path:line` reference, a
URL, a markdown table row, or the literal `UNVERIFIED:` prefix. The hook
cannot judge whether the evidence is real; it only refuses a bare
assurance where the user asked for proof.

Blocks (exit 2) so the turn is rewritten with the evidence. Fail-open on
any read/parse error; `stop_hook_active` allows the rewrite through.
"""
from __future__ import annotations

import json
import os
import re

OUTPUT_VERBS = ("repro", "reproduce", "test", "rerun", "re-run", "run", "regenerate", "prove")
LINK_OK_VERBS = ("run", "regenerate", "show")
DESTRUCTIVE_VERBS = ("delete", "revert")

NAMED_VERB_RE = re.compile(
    r"(?:^|[.;:!?,]\s*|\b(?:please|pls|then|now|and|just|go|can you|could you|you need to|fix(?: the)?)\s+)"
    r"(repro|reproduce|tests?|rerun|re-run|run|regenerate|prove|show|delete|revert)\b",
    re.IGNORECASE,
)
STOP_RE = re.compile(r"^\s*stop\b", re.IGNORECASE)
STOP_MAX_WORDS = 8

PROOF_RE = re.compile(
    r"\b(?:prove it|show me (?:the )?(?:proof|evidence|output|the run|it running)|are you sure|"
    r"did (?:you|it) (?:actually |really )?(?:run|test|verify|check|pass)|how do you know|"
    r"where(?:'s| is) the (?:proof|evidence|output)|show your work)\b",
    re.IGNORECASE,
)
PROOF_POLL_THRESHOLD = 2

FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
FILE_LINE_RE = re.compile(r"\b[\w./-]+\.[A-Za-z]{1,5}:\d+\b")
URL_RE = re.compile(r"https?://\S+")
TABLE_ROW_RE = re.compile(r"(?m)^\s*\|.*\|\s*$")
UNVERIFIED_RE = re.compile(r"\bUNVERIFIED:", re.IGNORECASE)
DESTRUCTIVE_CMD_RE = re.compile(
    r"(?:^|\s|\||&&|;)(?:rm|unlink|trash|git\s+(?:rm|revert|reset|restore|checkout|clean|stash))\b",
    re.IGNORECASE,
)
MUTATING_TOOLS = {"Bash", "Edit", "Write", "MultiEdit", "NotebookEdit", "StrReplace"}

SYSTEM_INJECTED_PREFIXES = (
    "<command-",
    "<task-notification",
    "<local-command",
    "<system",
    "<user-prompt-submit-hook",
    "This session is being continued",
    "Base directory for this skill",
    "[IMPORTANT: User invoked",
    "Stop hook feedback:",
    "PreToolUse hook",
    "PostToolUse hook",
    "UserPromptSubmit hook",
)


def _text_of(data: dict) -> str | None:
    message = data.get("message")
    content = message.get("content") if isinstance(message, dict) else data.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        return "\n".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    return None


def _is_human_line(data: dict) -> str | None:
    if not isinstance(data, dict) or data.get("type") != "user":
        return None
    text = _text_of(data)
    if not text or not text.strip():
        return None
    if text.lstrip().startswith(SYSTEM_INJECTED_PREFIXES):
        return None
    if "[Request interrupted by user" in text:
        return None
    return text


def read_transcript(transcript_path: str) -> tuple[list[str], list[dict]]:
    """(all human messages in order, tool_use blocks after the last one)."""
    humans: list[str] = []
    tool_uses: list[dict] = []
    with open(transcript_path, encoding="utf-8") as handle:
        for line in handle:
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = _is_human_line(data)
            if text is not None:
                humans.append(text)
                tool_uses = []
                continue
            if not isinstance(data, dict) or data.get("type") != "assistant":
                continue
            message = data.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_uses.append(block)
    return humans, tool_uses


def named_verbs(text: str) -> list[str]:
    verbs = [m.group(1).lower().rstrip("s") for m in NAMED_VERB_RE.finditer(text or "")]
    if STOP_RE.match(text or "") and len((text or "").split()) <= STOP_MAX_WORDS:
        verbs.append("stop")
    return verbs


def proof_poll_count(humans: list[str]) -> int:
    return sum(1 for text in humans if PROOF_RE.search(text))


def has_output_evidence(message: str) -> bool:
    return bool(FENCE_RE.search(message) or FILE_LINE_RE.search(message))


def has_link_evidence(message: str) -> bool:
    return bool(URL_RE.search(message) or TABLE_ROW_RE.search(message))


def bash_commands(tool_uses: list[dict]) -> list[str]:
    out = []
    for block in tool_uses:
        if block.get("name") == "Bash":
            command = (block.get("input") or {}).get("command")
            if isinstance(command, str):
                out.append(command)
    return out


def missing_evidence(verbs: list[str], polled: bool, message: str, tool_uses: list[dict]) -> str | None:
    """Return what is missing, or None when the reply carries the evidence."""
    if UNVERIFIED_RE.search(message) or message.rstrip().endswith("?"):
        return None
    output_ok = has_output_evidence(message)
    link_ok = output_ok or has_link_evidence(message)
    if polled and not link_ok:
        return "the user has asked for proof more than once this session; paste the command and its real output (fenced), a file:line, or a URL, or prefix the claim with `UNVERIFIED:`"
    for verb in verbs:
        if verb == "stop":
            mutating = [b.get("name") for b in tool_uses if b.get("name") in MUTATING_TOOLS]
            if mutating:
                return f"the user said stop, but this turn still ran {len(mutating)} mutating tool call(s) ({', '.join(sorted(set(mutating)))}); stop means stop"
            continue
        if verb in DESTRUCTIVE_VERBS:
            if any(DESTRUCTIVE_CMD_RE.search(c) for c in bash_commands(tool_uses)):
                continue
            if any(DESTRUCTIVE_CMD_RE.search(c) for c in re.findall(r"`([^`]+)`", message)):
                continue
            return f"the user asked to {verb}, but no delete/revert command ran this turn and the reply shows none; show the exact command, or say what blocked it"
        if verb in LINK_OK_VERBS:
            if link_ok:
                continue
            return f"the user asked to {verb}, but the reply carries no fenced output, file:line, URL, or table; show what happened"
        if verb in OUTPUT_VERBS:
            if output_ok:
                continue
            return f"the user asked to {verb}, but the reply carries no fenced command+output or file:line; a bare pass/done claim is false until the real output is in this message"
    return None


def decide(payload: dict) -> str | None:
    """Return blocking feedback, or None to let the turn finish."""
    if payload.get("stop_hook_active"):
        return None
    message = payload.get("last_assistant_message") or ""
    transcript_path = payload.get("transcript_path") or payload.get("transcriptPath") or ""
    if not message or not transcript_path or not os.path.isfile(transcript_path):
        return None
    humans, tool_uses = read_transcript(transcript_path)
    if not humans:
        return None
    last = humans[-1]
    verbs = named_verbs(last)
    polled = bool(PROOF_RE.search(last)) and proof_poll_count(humans) >= PROOF_POLL_THRESHOLD
    if not verbs and not polled:
        return None
    reason = missing_evidence(verbs, polled, message, tool_uses)
    if not reason:
        return None
    named = ", ".join(sorted(set(verbs))) or "proof"
    return (
        f"named-verb-guard ({named}): {reason}. Per CLAUDE.md named constraints: obey the "
        "named verb and put the evidence in the same message."
    )
