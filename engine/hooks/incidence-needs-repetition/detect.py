"""incidence-needs-repetition: a claim about behaviour ACROSS runs needs more than one run.

The sibling guard `hedge-runs-prove-it` catches the absence of confidence --
"probably", "should work", the `{{CAT-UNVERIFIED}}` tag. This one catches the opposite and
more dangerous shape: a confident claim whose subject is incidence.

"Deterministic", "flaky", "every run", "consistently" are not claims about
what code says; they are claims about the distribution of what it does when
run repeatedly. A single execution cannot support one, however green it was,
and neither can a `file:line` -- source proves what code says, never what it
does across runs. That is why the sibling's evidence bar, which accepts a
bare `file.ts:42`, cannot cover this shape.

The bar here is a declared sample size of two or more: a pasted "12
iterations", an "8/12 runs" ratio, or the same command actually invoked
twice in the turn. A well-formed `{{CAT-UNVERIFIED}}` tag also clears it, because it stops
the claim being asserted at all.

Incidence words quoted rather than claimed are out of scope, as is any run
inside a fence. Judgment stays with the model; this file matches shapes and
fails open.
"""
from __future__ import annotations

import json
import re
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_markers"))

import markers  # noqa: E402


INCIDENCE_RE = re.compile(
    r"\bnon-?deterministic\b|\bdeterministic(?:ally)?\b|\bflak(?:y|e|es|iness)\b|"
    r"\bintermittent(?:ly)?\b|\bevery run\b|\beach run\b|\bevery time\b|"
    r"\breliably\b|\bconsistently\b|\bnever flakes?\b|\bno longer flakes?\b|"
    r"\bstable across\b|\brace-free\b",
    re.IGNORECASE,
)

REPETITION_EVIDENCE_RE = re.compile(
    r"\b(?:[2-9]|\d{2,})\s*(?:x\s*)?(?:iterations?|runs?|samples?|trials?|times)\b|"
    r"\b\d+\s*/\s*(?:[2-9]|\d{2,})\s*(?:runs?|iterations?|samples?|trials?)\b|"
    r"\b\d+\s+of\s+(?:[2-9]|\d{2,})\s+(?:runs?|iterations?|samples?|trials?)\b|"
    r"\bruns_under_[\w,]+=\d+/\d+|\bspread\s*=\s*[\d,]+|"
    r"\{\{CAT-UNVERIFIED\b[^}]*cannot\s+verify\s*:\s*\S",
    re.IGNORECASE,
)

QUOTE_SPAN_RES = (
    re.compile(r"```.*?```", re.DOTALL),
    re.compile(r"`[^`\n]+`"),
    re.compile(r'"[^"\n]*"'),
)

MESSAGE = (
    "incidence-needs-repetition: this reply claims behaviour across runs ({term}) "
    "but shows evidence from a single run. A green run, and a file:line, both prove "
    "what happened once -- neither is a distribution. Re-run the measurement at least "
    "twice and paste the spread (e.g. \"12 iterations ... spread=...\"), or prefix the "
    "claim with `{tag}`."
)


def quoted_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for pattern in QUOTE_SPAN_RES:
        spans.extend((m.start(), m.end()) for m in pattern.finditer(text or ""))
    return spans


def _inside_quoted_span(position: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= position < end for start, end in spans)


def incidence_claims(text: str) -> list[str]:
    """Incidence words that are claimed rather than cited."""
    hits: list[str] = []
    spans = quoted_spans(text or "")
    for match in INCIDENCE_RE.finditer(text or ""):
        if _inside_quoted_span(match.start(), spans):
            continue
        hits.append(match.group(0))
    return hits


def has_repetition_evidence(text: str) -> bool:
    return bool(REPETITION_EVIDENCE_RE.search(text or ""))


def parse_lines(raw_lines) -> list[dict]:
    parsed: list[dict] = []
    for raw in raw_lines:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict):
            parsed.append(data)
    return parsed


def _is_human_user_line(data: dict) -> bool:
    if data.get("type") != "user":
        return False
    message = data.get("message")
    if not isinstance(message, dict):
        return False
    content = message.get("content")
    if isinstance(content, list):
        return any(isinstance(part, dict) and part.get("type") == "text" for part in content)
    return isinstance(content, str) and bool(content.strip())


def repeated_command_this_turn(lines: list[dict]) -> bool:
    """True when one Bash command ran two or more times since the last human turn."""
    turn_start = 0
    for i, data in enumerate(lines):
        if _is_human_user_line(data):
            turn_start = i
    seen: dict[str, int] = {}
    for data in lines[turn_start:]:
        if data.get("type") != "assistant":
            continue
        message = data.get("message")
        if not isinstance(message, dict):
            continue
        for part in message.get("content") or []:
            if not isinstance(part, dict) or part.get("type") != "tool_use":
                continue
            if part.get("name") != "Bash":
                continue
            command = (part.get("input") or {}).get("command")
            if not isinstance(command, str):
                continue
            key = " ".join(command.split())
            seen[key] = seen.get(key, 0) + 1
            if seen[key] >= 2:
                return True
    return False


def decide_from_lines(message: str, lines: list[dict]) -> str | None:
    claims = incidence_claims(message)
    if not claims:
        return None
    if has_repetition_evidence(message):
        return None
    if repeated_command_this_turn(lines):
        return None
    return MESSAGE.format(tag=markers.TAG_TEMPLATE, term=", ".join(f'"{c}"' for c in claims[:3]))


def decide(payload: dict) -> str | None:
    """Return blocking feedback for the Stop event, or None to let the turn finish."""
    if payload.get("stop_hook_active"):
        return None
    message = payload.get("last_assistant_message") or ""
    if not incidence_claims(message):
        return None
    if has_repetition_evidence(message):
        return None
    transcript_path = payload.get("transcript_path") or payload.get("transcriptPath") or ""
    lines: list[dict] = []
    if transcript_path:
        try:
            with open(transcript_path, encoding="utf-8") as handle:
                lines = parse_lines(handle)
        except OSError:
            return None
    return decide_from_lines(message, lines)
