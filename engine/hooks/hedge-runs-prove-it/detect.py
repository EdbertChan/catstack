"""hedge-runs-prove-it: unproven code, state, and capability claims must be verified.

Three shapes, three bars.

A hedge -- "I think", "I believe", "probably", "should work", "presumably",
or a `{{CAT-UNVERIFIED}}` tag next to a code noun (a path, a backticked name,
test, CI, build, bug, fix, script, hook, PR, merge, branch, commit) --
means the agent has a check it has not run. The reply passes only when the
turn ran a verification tool (Bash, Read, Grep, Glob) or the `{{CAT-UNVERIFIED}}`
clause says why it cannot be verified ("cannot verify: no network").

An unhedged diagnosis -- "it's a zombie", "that's the bug", "the root cause
is X", "the worker is hung", "this is why it's slow" -- asserts live system
state with no hedge word at all, so the hedge bar never sees it. Confidence
is the more dangerous shape, not the safer one: the claim carries no signal
that a check is outstanding. Running a tool in the turn does not clear it,
because a projection that omits a field is not proof the state is absent.
Only instrument-level proof in the same message clears it: pasted output, a
`file:line`, a pid, an exit code, or an explicit `{{CAT-UNVERIFIED}}` tag.

A capability enumeration copied from error-shaped tool output is not proof of
what another system accepts or supports. A reply that repeats two or more of
those values beside a capability verb is blocked unless a non-error tool result
also supplied them, or the reply attributes the list as fallback/error data.

Hedges about things that are not code or state (a company's motive, a
filing date) are out of scope, and so is either shape quoted rather than
claimed -- anywhere inside a double-quoted, backticked or single-quoted run,
not merely as its first token -- along with diagnoses inside a fence, a
blockquote, or a hypothetical. Judgment stays with the model; this file
matches shapes and fails open.
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_markers"))

import markers  # noqa: E402

HEDGE_RE = re.compile(
    r"\bI think\b|\bI believe\b|\bprobably\b|\bshould work\b|\bpresumably\b|"
    r"\bI suspect\b|\bI'?d guess\b|\bmy guess is\b|\bUNVERIFIED:",
    re.IGNORECASE,
)
CODE_NOUN_RE = re.compile(
    r"`[^`\n]+`|\b[\w./-]+\.(?:py|ts|js|mjs|sh|json|yml|yaml|md|toml|mdc)\b|"
    r"\b(?:tests?|CI|build|bug|fix(?:ed|es)?|script|hook|PRs?|merge[ds]?|branch|commit|"
    r"worktree|tree|repo|function|module|config|install|deploy|pipeline|gate|suite|"
    r"error|exception|traceback|import|dependency|symlink|file)\b",
    re.IGNORECASE,
)
REASON_RE = re.compile(
    r"\b(?:cannot|can'?t|could not|couldn'?t|unable to|no way to|not possible to|"
    r"would need|requires|needs|without|not run|did not run|didn'?t run|no access|"
    r"no network|offline|not reachable|sandbox)\b",
    re.IGNORECASE,
)
PROXIMITY = 200
VERIFY_TOOLS = {"Bash", "Read", "Grep", "Glob", "Monitor", "WebFetch"}
QUOTED_BEFORE = ('"', "'", "`")

DIAGNOSIS_RE = re.compile(
    r"(?:\b(?:it'?s|that'?s|this\s+is|they'?re|the\s+[\w-]+(?:\s+[\w-]+)?\s+is)\s+"
    r"(?:just\s+|simply\s+|actually\s+|basically\s+|clearly\s+|a\s+|an\s+|the\s+)*"
    r"(?:zombie|hung|hanging|stuck|wedged|deadlocked|dead(?!\s+code)|crashed|"
    r"leaking|thrashing|starved|orphaned|frozen|spinning|silently\s+failing|"
    r"corrupt(?:ed)?|misconfigured)\b)|"
    r"(?:\b(?:that'?s|this\s+is|here'?s)\s+(?:the|your|our|my)\s+"
    r"(?:bug|root\s+cause|cause|culprit|problem|issue|failure)\b)|"
    r"(?:\bthe\s+(?:root\s+)?cause\s+is\b)|"
    r"(?:\bthe\s+reason\s+is\b)|"
    r"(?:\bwhat'?s\s+(?:happening|going\s+on)\s+is\b)|"
    r"(?:\b(?:that|this)(?:'?s|\s+is)\s+why\s+(?:it|its|it'?s|the|they|that|this)\b)",
    re.IGNORECASE,
)
RUNTIME_NOUN_RE = re.compile(
    r"\b(?:process(?:es)?|pids?|threads?|workers?|tasks?|jobs?|runs?|runners?|"
    r"daemons?|services?|servers?|hosts?|containers?|pods?|nodes?|pools?|"
    r"queues?|slots?|workflows?|sessions?|agents?|sockets?|ports?|"
    r"connections?|locks?|loops?|requests?|cpu|memory|disk|cache|database|db|"
    r"quer(?:y|ies)|logs?|streams?|builds?|tests?|suites?|CI|pipelines?|"
    r"hooks?|scripts?|commands?|replay)\b",
    re.IGNORECASE,
)
INSTRUMENT_EVIDENCE_RE = re.compile(
    r"```|\{\{CAT-UNVERIFIED\b|/proc/\d+|"
    r"\b[\w./-]+\.[A-Za-z]{1,6}:\d+\b|"
    r"\bpids?\b\s*[:=#]?\s*\d+|\bMainPID\b|"
    r"\bexit\s+(?:code|status)\b|\bexit[_-]?code\b",
    re.IGNORECASE,
)
DIAGNOSIS_LOOKBACK_RE = re.compile(
    r"\b(?:if|unless|whether|suppose|assuming|in case|maybe|perhaps|"
    r"might\s+be|could\s+be|may\s+be|not\s+sure|unclear)\b[^.!?\n]*$",
    re.IGNORECASE,
)
LOOKBACK = 120
FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
BLOCKQUOTE_RE = re.compile(r"(?m)^\s*>.*$")
DOUBLE_QUOTE_RE = re.compile(r'"[^"]*"', re.DOTALL)
BACKTICK_RE = re.compile(r"`[^`]*`", re.DOTALL)
SINGLE_QUOTE_RE = re.compile(r"(?<![A-Za-z0-9])'(?![\s'])[^'\n]*(?<!\s)'(?![A-Za-z0-9])")
QUOTE_SPAN_RES = (DOUBLE_QUOTE_RE, BACKTICK_RE, SINGLE_QUOTE_RE)

MESSAGE = (
    "hedge-runs-prove-it: this reply hedges about code or repo state ({hedge}) and "
    "the turn ran no verification (no Bash / Read / Grep). Run prove-it now: verify in "
    "this turn, or write `{tag}`."
)

DIAGNOSIS_MESSAGE = (
    "hedge-runs-prove-it: this reply asserts a diagnosis about live system state "
    "({claim}) with no instrument-level proof in the same message. An unhedged "
    "root-cause claim is the dangerous shape, not the hedged one -- nothing in it "
    "signals an outstanding check -- and a projection that omits a field is not "
    "proof the state is absent. Attach the instrument output here: pasted ps / "
    "strace / /proc output, a live query's real result, a pid, an exit code, or a "
    "file:line. Otherwise tag the claim: `{tag}`."
)

ERROR_OUTPUT_RE = re.compile(
    r"\b(?:error|exception|fatal|failure|failed|invalid|unsupported|traceback)\b|"
    r"\bnot\s+supported\b",
    re.IGNORECASE,
)
BRACKETED_ENUM_RE = re.compile(r"\[([^\[\]\n]+)\]")
COMMA_ENUM_RE = re.compile(
    r"(?<![A-Za-z0-9_.+/@:-])"
    r"([A-Za-z0-9][A-Za-z0-9_.+/@:-]*(?:\s*,\s*[A-Za-z0-9][A-Za-z0-9_.+/@:-]*)+)"
    r"(?![A-Za-z0-9_.+/@:-])"
)
ENUM_VALUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+/@:-]*$")
CAPABILITY_RE = re.compile(
    r"\b(?:accepts?|supports?|known\s+models?|valid|only)\b",
    re.IGNORECASE,
)
CAPABILITY_ATTRIBUTION_RE = re.compile(
    r"\b(?:fallback|hardcoded|hard-coded|built[ -]in|retract(?:ed|ing|ion)?)\b|"
    r"\b(?:in|from)\s+(?:the|this|that|an)\s+error\b|"
    r"\b(?:the|this|that)\s+error\s+(?:says|lists|reported|showed)\b",
    re.IGNORECASE,
)
VALUE_CHARS = "A-Za-z0-9_.+/@:-"

CAPABILITY_MESSAGE = (
    "hedge-runs-prove-it: this reply asserts capability values copied only from "
    "error-shaped tool output ({values}). Verify them from a non-error source, or "
    "attribute them as an error, fallback, hardcoded, or built-in list."
)


def _sentence_after(text: str, start: int) -> str:
    end = len(text)
    for stop in (".\n", "\n\n"):
        idx = text.find(stop, start)
        if idx != -1:
            end = min(end, idx)
    return text[start:end]


def quoted_spans(text: str) -> list[tuple[int, int]]:
    """Character ranges of double-quoted, backticked and single-quoted runs.

    A single quote only opens a span when it is not an apostrophe: "it's",
    "don't" and "the workers' pool" all keep their quote as a letter, so a
    hedge beside one is not exempt on that basis.
    """
    spans: list[tuple[int, int]] = []
    for pattern in QUOTE_SPAN_RES:
        spans.extend((m.start(), m.end()) for m in pattern.finditer(text or ""))
    return spans


def _inside_quoted_span(position: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= position < end for start, end in spans)


def code_hedges(text: str) -> list[str]:
    """Hedge phrases near a code noun that lack a cannot-verify reason.

    A hedge anywhere inside a quoted run is someone citing the word, not
    claiming it, so the whole span is exempt rather than only its first
    token. The span is tested by containment and never stripped: a
    backticked name is itself a code noun, so removing the span would take
    the proximity signal with it.
    """
    hits: list[str] = []
    spans = quoted_spans(text or "")
    for match in HEDGE_RE.finditer(text or ""):
        if _inside_quoted_span(match.start(), spans):
            continue
        if match.start() and text[match.start() - 1] in QUOTED_BEFORE:
            continue
        window = text[max(0, match.start() - PROXIMITY): match.end() + PROXIMITY]
        if not CODE_NOUN_RE.search(window):
            continue
        if match.group(0).upper().startswith("UNVERIFIED") and markers.well_formed_tags(
            text[max(0, match.start() - len("{{CAT-")): match.end() + PROXIMITY]
        ):
            continue
        hits.append(match.group(0))
    return hits


def _diagnosis_text(text: str) -> str:
    cleaned = FENCE_RE.sub(" ", text or "")
    cleaned = BLOCKQUOTE_RE.sub(" ", cleaned)
    for pattern in QUOTE_SPAN_RES:
        cleaned = pattern.sub(" ", cleaned)
    return cleaned


def diagnosis_claims(text: str) -> list[str]:
    """Unhedged diagnoses of live system state carrying no same-message proof."""
    if not text or INSTRUMENT_EVIDENCE_RE.search(text):
        return []
    cleaned = _diagnosis_text(text)
    hits: list[str] = []
    for match in DIAGNOSIS_RE.finditer(cleaned):
        window = cleaned[max(0, match.start() - PROXIMITY): match.end() + PROXIMITY]
        if not RUNTIME_NOUN_RE.search(window):
            continue
        if DIAGNOSIS_LOOKBACK_RE.search(cleaned[max(0, match.start() - LOOKBACK): match.start()]):
            continue
        hits.append(match.group(0))
    return hits


def _text_content(data: dict) -> str:
    message = data.get("message")
    content = message.get("content") if isinstance(message, dict) else data.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def _is_human_user_line(data: dict) -> bool:
    if data.get("type") != "user":
        return False
    text = _text_content(data)
    return bool(text.strip()) and not text.lstrip().startswith("<")


def _tool_result_text(block: dict) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    chunks: list[str] = []
    for item in content:
        if isinstance(item, str):
            chunks.append(item)
        elif isinstance(item, dict) and isinstance(item.get("text"), str):
            chunks.append(item["text"])
    return "\n".join(chunks)


def _tool_results(lines: list[dict]):
    for data in lines:
        message = data.get("message")
        content = message.get("content") if isinstance(message, dict) else data.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                yield block, _tool_result_text(block)


def _enumerated_values(text: str) -> set[str]:
    runs = [match.group(1) for match in BRACKETED_ENUM_RE.finditer(text or "")]
    runs.extend(match.group(1) for match in COMMA_ENUM_RE.finditer(text or ""))
    values: set[str] = set()
    for run in runs:
        for raw_value in run.split(","):
            value = raw_value.strip().strip("'\"`")
            if len(value) >= 2 and ENUM_VALUE_RE.fullmatch(value):
                values.add(value.lower())
    return values


def _value_occurs(text: str, value: str) -> bool:
    return bool(re.search(
        rf"(?<![{VALUE_CHARS}]){re.escape(value)}(?![{VALUE_CHARS}])",
        text or "",
        re.IGNORECASE,
    ))


def error_only_capability_values(lines: list[dict]) -> set[str]:
    """Enumerated values whose tool-result sources are all error-shaped."""
    error_values: set[str] = set()
    non_error_results: list[str] = []
    for block, text in _tool_results(lines):
        error_shaped = bool(block.get("is_error") or ERROR_OUTPUT_RE.search(text))
        if error_shaped:
            error_values.update(_enumerated_values(text))
        else:
            non_error_results.append(text)
    return {
        value for value in error_values
        if not any(_value_occurs(text, value) for text in non_error_results)
    }


def _capability_feedback(message: str, lines: list[dict]) -> str | None:
    if not CAPABILITY_RE.search(message or "") or CAPABILITY_ATTRIBUTION_RE.search(message or ""):
        return None
    values = error_only_capability_values(lines)
    for verb in CAPABILITY_RE.finditer(message):
        window = message[max(0, verb.start() - PROXIMITY): verb.end() + PROXIMITY]
        repeated = sorted(value for value in values if _value_occurs(window, value))
        if len(repeated) >= 2:
            return CAPABILITY_MESSAGE.format(values=", ".join(repeated[:4]))
    return None


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


def verified_this_turn(lines: list[dict]) -> bool:
    turn_start = 0
    for i, data in enumerate(lines):
        if _is_human_user_line(data):
            turn_start = i
    for data in lines[turn_start:]:
        if data.get("type") != "assistant":
            continue
        message = data.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") in VERIFY_TOOLS:
                return True
    return False


def _diagnosis_feedback(message: str) -> str | None:
    claims = diagnosis_claims(message)
    if not claims:
        return None
    return DIAGNOSIS_MESSAGE.format(tag=markers.TAG_TEMPLATE, claim=", ".join(f'"{c}"' for c in claims[:3]))


def decide_from_lines(message: str, lines: list[dict]) -> str | None:
    diagnosis = _diagnosis_feedback(message)
    if diagnosis:
        return diagnosis
    hedges = code_hedges(message)
    if hedges and not verified_this_turn(lines):
        return MESSAGE.format(
            tag=markers.TAG_TEMPLATE,
            hedge=", ".join(f'"{h}"' for h in hedges[:3]),
        )
    return _capability_feedback(message, lines)


def decide(payload: dict) -> str | None:
    """Return blocking feedback for the Stop event, or None to let the turn finish."""
    if payload.get("stop_hook_active"):
        return None
    message = payload.get("last_assistant_message") or ""
    diagnosis = _diagnosis_feedback(message)
    if diagnosis:
        return diagnosis
    if not code_hedges(message) and not CAPABILITY_RE.search(message):
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
