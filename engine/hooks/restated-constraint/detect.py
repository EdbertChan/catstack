"""restated-constraint: did the user just repeat a constraint they already named?

A constraint is a user sentence carrying must / never / always / don't /
do not / only / one-X-per-Y. When the incoming prompt carries one and an
earlier human message in the same transcript already carried the same
constraint (same content words, the same constraint clause, or the same
hyphenated term), the user is restating something the agent should have
kept applying. That is a FAIL-class signal, not a preference: the fix is
to apply the constraint before replying, not to acknowledge it again.

Deterministic. No LLM. Advisory only (UserPromptSubmit additionalContext).
Fail-open: any read/parse error stays silent.
"""
from __future__ import annotations

import json
import os
import re

CONSTRAINT_RE = re.compile(
    r"\b(?:must(?:\s+not)?|never|always|don'?t|do\s+not|should\s+(?:never|not)|"
    r"no\s+more|not\s+allowed|only\s+ever|one\s+\w+\s+per\s+\w+|"
    r"should|again|as\s+i\s+said|i\s+(?:already\s+)?(?:told|asked)\s+you|i\s+said|remember)\b",
    re.IGNORECASE,
)
KERNEL_RE = re.compile(
    r"\b(?:must(?:\s+not)?|never|always|don'?t|do\s+not|should\s+(?:never|not))\s+"
    r"((?:[\w'-]+\s+){0,5}[\w'-]+)",
    re.IGNORECASE,
)
ONE_PER_RE = re.compile(r"\bone\s+\w+\s+per\s+(?:\w+\s+){0,2}\w+", re.IGNORECASE)
HYPHEN_TERM_RE = re.compile(r"\b[a-z]+(?:-[a-z]+)+\b", re.IGNORECASE)
WORD_RE = re.compile(r"[a-z][a-z'-]*", re.IGNORECASE)

STOPWORDS = frozenset(
    """
    a an the and or but if then than that this these those there here it its
    is are was were be been being have has had do does did done doing not no
    yes you your yours we our ours i me my mine he she they them their his her
    what which who whom whose when where why how all any both each few more
    most other some such only own same so too very can will just should would
    could must never always dont don't into onto from with without about above
    below over under again further once also please make sure like want need
    lets let's okay ok thanks thank going get got still already keep keeps
    ever every for out off up down while during before after between through
    because until unless since across per one two three
    """.split()
)

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

GENERIC_HYPHEN_TERMS = frozenset(
    """
    one-off so-called well-known long-term short-term high-level low-level
    real-time built-in read-only open-source follow-up up-to-date to-do
    end-to-end re-run re-read e-mail non-blocking pre-existing
    """.split()
)
MIN_HYPHEN_PART = 3

JACCARD_THRESHOLD = 0.5
MIN_CONTENT_WORDS = 4
TEMPLATE_NEAR_DUP_LIMIT = 3


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).casefold()


def content_words(text: str) -> list[str]:
    words = []
    for raw in WORD_RE.findall((text or "").replace("-", " ")):
        word = raw.casefold().strip("'")
        if len(word) >= 3 and word not in STOPWORDS:
            words.append(word)
    return words


def kernels(text: str) -> list[frozenset[str]]:
    found = []
    for match in KERNEL_RE.finditer(text or ""):
        words = frozenset(content_words(match.group(1)))
        if len(words) >= 2:
            found.append(words)
    for match in ONE_PER_RE.finditer(text or ""):
        words = frozenset(content_words(match.group(0)))
        if len(words) >= 2:
            found.append(words)
    return found


def hyphen_terms(text: str) -> set[str]:
    out = set()
    for raw in HYPHEN_TERM_RE.findall(text or ""):
        term = raw.casefold()
        parts = term.split("-")
        if term in GENERIC_HYPHEN_TERMS or any(len(p) < MIN_HYPHEN_PART for p in parts):
            continue
        out.add(term.replace("-", " "))
    return out


def jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    union = sa | sb
    return len(sa & sb) / len(union) if union else 0.0


def has_constraint(text: str) -> bool:
    return bool(CONSTRAINT_RE.search(text or ""))


def is_restatement(current: str, prior: str) -> str | None:
    """Return the signal name when `prior` already carried `current`'s constraint.

    Never reports near-duplicates; `find_prior_statement` handles those so a
    workflow template the user re-sends every turn can be rate-limited."""
    cur_words = content_words(current)
    prior_words = content_words(prior)
    if len(cur_words) < MIN_CONTENT_WORDS or not prior_words:
        return None
    prior_set = set(prior_words)
    cur_hyphens = hyphen_terms(current)
    prior_hyphens = hyphen_terms(prior)
    prior_norm = " ".join(prior_words)
    for term in cur_hyphens:
        if term in prior_hyphens or f" {term} " in f" {prior_norm} ":
            return "shared-hyphenated-term"
    cur_norm = " ".join(cur_words)
    for term in prior_hyphens:
        if f" {term} " in f" {cur_norm} ":
            return "shared-hyphenated-term"
    if not has_constraint(prior):
        return None
    for kernel in kernels(current):
        if kernel <= prior_set:
            return "same-constraint-clause"
    return None


def extract_prompt_text(payload: dict) -> str:
    for key in ("prompt", "user_prompt", "userPrompt", "message", "text"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


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


def human_user_messages(transcript_path: str) -> list[tuple[str | None, str]]:
    """Every human-authored user message as (iso_ts, text), in order."""
    out: list[tuple[str | None, str]] = []
    with open(transcript_path, encoding="utf-8") as handle:
        for line in handle:
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict) or data.get("type") != "user":
                continue
            text = _text_of(data)
            if not text or not text.strip():
                continue
            if text.lstrip().startswith(SYSTEM_INJECTED_PREFIXES):
                continue
            if "[Request interrupted by user" in text:
                continue
            out.append((data.get("timestamp"), text))
    return out


def find_prior_statement(current: str, priors: list[tuple[str | None, str]]) -> dict | None:
    """First earlier human message that already carried this constraint.

    A near-duplicate prior fires only while the user has re-sent that text
    fewer than TEMPLATE_NEAR_DUP_LIMIT times; past that it is a workflow
    template, and only the other signals (a hyphenated term, the same
    constraint clause, a shared phrase) may match against non-template
    priors."""
    if not has_constraint(current):
        return None
    cur_norm = normalize(current)
    if priors and normalize(priors[-1][1]) == cur_norm:
        priors = priors[:-1]
    cur_words = content_words(current)
    if len(cur_words) < MIN_CONTENT_WORDS:
        return None
    near_dups = 0
    first_near_dup = None
    for index, (ts, text) in enumerate(priors, start=1):
        if jaccard(cur_words, content_words(text)) >= JACCARD_THRESHOLD:
            near_dups += 1
            if first_near_dup is None:
                first_near_dup = {"turn": index, "timestamp": ts, "excerpt": text.strip()[:120], "signal": "near-duplicate"}
            continue
        signal = is_restatement(current, text)
        if signal:
            return {"turn": index, "timestamp": ts, "excerpt": text.strip()[:120], "signal": signal}
    if first_near_dup is not None and near_dups < TEMPLATE_NEAR_DUP_LIMIT:
        return first_near_dup
    return None


def reminder_text(hit: dict) -> str:
    when = f" ({hit['timestamp']})" if hit.get("timestamp") else ""
    return (
        f"restated-constraint: this constraint was already named at turn {hit['turn']}{when} "
        f"[{hit['signal']}]: \"{hit['excerpt']}\". A repeated constraint is a FAIL-class "
        "signal, not a preference: apply it before replying, state what you changed to "
        "comply, and do not ask the user to restate it again."
    )


def decide(payload: dict) -> str | None:
    """Return the additionalContext text, or None to stay silent."""
    prompt = extract_prompt_text(payload if isinstance(payload, dict) else {})
    if not prompt or prompt.lstrip().startswith(SYSTEM_INJECTED_PREFIXES):
        return None
    if not has_constraint(prompt):
        return None
    transcript_path = payload.get("transcript_path") or payload.get("transcriptPath") or ""
    if not transcript_path or not os.path.isfile(transcript_path):
        return None
    priors = human_user_messages(transcript_path)
    hit = find_prior_statement(prompt, priors)
    if not hit:
        return None
    return reminder_text(hit)
