"""A summary that names a search is not a search that ran.

`hedge-runs-prove-it` fires when a hedge sits next to no verification tool at
all. `prove-it-ship-gate` fires on a done/shipped claim about a live surface.
Both pass a turn that ran twenty-four real commands and then reported a
twenty-fifth it never ran -- the confident, specific, false citation.

This hook closes that gap for the one family of commands where the claim is
literal enough to check mechanically: history search. `git log --grep`
searches commit messages; `git log -S/-G/-L`, `git log --follow`, and
`git blame` search the history of the code itself. `history-before-reversal`
already encodes that distinction, but only guards `git revert`. Here the
trigger is the claim, not the act.

Scope is deliberately narrow. Only backticked spans count, so prose never
matches. Only a sentence that also reports a result counts. A flag-only span
attaches to the nearest preceding base command, because
`git log --all --grep`/`-S` is how the shorthand is actually written.

A proposed command stays silent, and it takes two rules to keep that promise.
Bare "run" is not a report -- it is the imperative and the infinitive, as in
"next, run X" and "the fix is to run X" -- so only "ran" and the perfect
"have run" count. And an imperative is caught by position rather than by
keyword, since "Next, run `git log -S foo`" carries no instruction word at
all: a sentence opening with a base-form verb, optionally behind a
connective, proposes. Past-tense openers survive that rule untouched, because
the word boundary after the base form does not match an `-ed` ending, so
"Checked `git log -S foo` -- nothing" still reports.

Advisory: stderr plus exit 0. The citation may be sloppy shorthand rather
than a fabricated check, and that is the author's call to make. Fail-open on
any parse or IO error.
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_flags"))

from flags import enforcement_gate  # noqa: E402

BASES = (
    ("git log", re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?log\b")),
    ("git blame", re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?blame\b")),
    ("gh pr list", re.compile(r"\bgh\s+pr\s+list\b")),
    ("gh search", re.compile(r"\bgh\s+search\b")),
)

CODE_HISTORY_FLAGS = {
    "-S": re.compile(r"(?:^|\s)-S"),
    "-G": re.compile(r"(?:^|\s)-G"),
    "-L": re.compile(r"(?:^|\s)-L"),
    "--follow": re.compile(r"(?:^|\s)--follow\b"),
    "--grep": re.compile(r"(?:^|\s)--grep\b"),
    "--search": re.compile(r"(?:^|\s)--search\b"),
}

BACKTICK_RE = re.compile(r"`([^`\n]{1,120})`")
FLAG_ONLY_RE = re.compile(r"^-{1,2}[A-Za-z][\w-]*$")

ASSERTIVE_RE = re.compile(
    r"(?i)\b(?:ran|(?:have|has|had|[\u2019\']ve|[\u2019\']d)\s+run|"
    r"searched|swept|checked|class[- ]search|history[- ]search|"
    r"turned\s+up|came\s+back|returns?|returned|shows?|showed|found|no\s+hits?|"
    r"nothing|none|confirmed|verified|clean|empty)\b"
)

INSTRUCTION_RE = re.compile(
    r"(?i)\b(?:should|must|need\s+to|next\s+time|todo|consider|try|please|"
    r"would\s+(?:be|catch|find)|recommend|suggest|before\s+finalizing|"
    r"the\s+fix\s+is|supposed\s+to|"
    r"(?:told|telling|tells|asked|asking|asks|instructed|instructs|directed|"
    r"wants|wanted|expects|expected|requires|required|prompts|prompted)"
    r"\s+(?:me|us|you|it)\s+to|"
    r"let[\u2019\']?s|worth\s+running|follow[- ]up|"
    r"(?:you|we)\s+(?:can|could|may|might))\b"
)

IMPERATIVE_RE = re.compile(
    r"(?i)^\W*(?:(?:next|then|also|finally|first|now|afterwards?|instead|"
    r"and|so|optionally)\b[\s,:;-]*)*"
    r"(?:re-?)?(?:run|try|check|search|sweep|grep|look|see|confirm|verify|"
    r"consider|repeat)\b"
)

MESSAGE = (
    "claimed-search-not-run: this message cites {claimed} as a search that "
    "ran, but no Bash call in this session matches it. {ran}Either run it now "
    "and report what it returned, or drop the citation -- a named command is "
    "read as evidence, and `git log --grep` searches commit messages, not the "
    "history of the code."
)


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?;:\n])\s+", text or "") if s.strip()]


def claimed_searches(message: str) -> set[str]:
    """(base, flag) pairs the message cites, as 'base flag' strings."""
    claims: set[str] = set()
    for sentence in _sentences(message):
        if not ASSERTIVE_RE.search(sentence) or INSTRUCTION_RE.search(sentence):
            continue
        if IMPERATIVE_RE.match(sentence):
            continue
        base = None
        for span in BACKTICK_RE.findall(sentence):
            span = span.strip()
            matched_base = next((name for name, rx in BASES if rx.search(span)), None)
            if matched_base:
                base = matched_base
                for flag, rx in CODE_HISTORY_FLAGS.items():
                    if rx.search(span):
                        claims.add(f"{base} {flag}")
                continue
            if base and FLAG_ONLY_RE.match(span) and span in CODE_HISTORY_FLAGS:
                claims.add(f"{base} {span}")
    return claims


def _commands(transcript_path: str) -> list[str]:
    """Every Bash command string in the transcript. [] when unreadable."""
    try:
        with open(transcript_path, encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return []
    out: list[str] = []
    for raw in lines:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict) or data.get("type") != "assistant":
            continue
        message = data.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            command = (block.get("input") or {}).get("command")
            if isinstance(command, str):
                out.append(command)
    return out


def ran_search(claim: str, commands: list[str]) -> bool:
    base, flag = claim.rsplit(" ", 1)
    base_rx = next(rx for name, rx in BASES if name == base)
    flag_rx = CODE_HISTORY_FLAGS[flag]
    return any(base_rx.search(cmd) and flag_rx.search(cmd) for cmd in commands)


def find_unrun(message: str, transcript_path: str) -> list[str]:
    claims = claimed_searches(message)
    if not claims:
        return []
    commands = _commands(transcript_path)
    if not commands:
        return []
    return sorted(c for c in claims if not ran_search(c, commands))


def decide(payload: dict) -> str | None:
    if not enforcement_gate("claimed-search-not-run", payload.get("cwd")):
        return None
    if payload.get("stop_hook_active"):
        return None
    message = payload.get("last_assistant_message") or ""
    transcript_path = (
        payload.get("agent_transcript_path")
        or payload.get("transcript_path")
        or payload.get("transcriptPath")
        or ""
    )
    if not transcript_path:
        return None
    try:
        unrun = find_unrun(message, transcript_path)
    except Exception as exc:
        print(
            f"catstack-hook-error claimed-search-not-run: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return None
    if not unrun:
        return None
    claims = claimed_searches(message)
    did_run = sorted(claims.difference(unrun))
    ran = f"It did run {', '.join('`' + c + '`' for c in did_run)}. " if did_run else ""
    return MESSAGE.format(claimed=", ".join("`" + c + "`" for c in unrun), ran=ran)
