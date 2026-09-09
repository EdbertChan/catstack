"""history-claim-check: a claim about repo history is one git command away.

Durations, counts, authorship and never/always statements about code are the
cheapest facts to check and the easiest to feel certain about without checking.
That combination is what ships them into a PR body, where they become durable
and are read as measured.

Fires only on commands that write a PR title or body to GitHub. Everything else
passes untouched.
"""
from __future__ import annotations

import re
import shlex
from pathlib import Path

PUBLISH_RE = re.compile(
    r"\bgh\s+pr\s+(?:create|edit)\b|"
    r"\bgh\s+api\b[^|;\n]*\brepos/[^\s|;]+/pulls\b|"
    r"\bcreate-pr\.mjs\b",
)

CLAIMS = [
    (re.compile(r"\b(?:for|over|across|about|roughly|nearly|almost|~)?\s*"
                r"(?:\d+|a|one|two|three|four|five|six|seven|eight|nine|ten|twelve)"
                r"[-\s](?:month|year|week|day)s?\b", re.I),
     "duration", "git log -S '<string>' --format='%ad %h' --date=short"),
    (re.compile(r"\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+"
                r"(?:\w+\s+){0,2}"
                r"(?:reflect|review|pass|passes|session|sessions|commit|commits|PRs?|"
                r"attempt|attempts|instance|instances|file|files|time|times)\b"
                r"[^.\n]{0,80}?"
                r"\b(?:found|produced|said|flagged|fixed|landed|reported|caught|missed|"
                r"ever|never|loaded|ran)\b", re.I),
     "count", "count them: git log --grep=... | wc -l, or grep -c"),
    (re.compile(r"\b(?:written|authored|introduced|added|created)\s+by\b", re.I),
     "authorship", "git log --format='%an <%ae>' -- <path> | sort -u"),
    (re.compile(r"\b(?:never|always)\s+(?:\w+\s+){0,3}"
                r"(?:loaded|ran|run|fired|worked|existed|shipped|merged|landed|applied|called)\b",
                re.I),
     "never/always", "git log --all -S '<token>' -- <path>"),
    (re.compile(r"\b(?:first|last)\s+(?:introduced|added|appeared|broken|failing)\b", re.I),
     "first/last occurrence", "git log --all -S '<token>' --reverse --format='%ad %h'"),
]

EVIDENCE = re.compile(
    r"```|\bgit (?:log|blame|show|rev-list)\b|\b[0-9a-f]{7,40}\b|\bUNVERIFIED\b", re.I
)
WINDOW = 6

MESSAGE = (
    "history-claim-check: this PR body states {n} claim(s) about repo history with no "
    "adjacent evidence. Each is one git command:\n{detail}\n"
    "Run the command, paste its output beside the claim, or write UNVERIFIED: before it. "
    "A wrong duration or count in a PR body is read as measured and outlives the session."
)


def is_publication(text: str) -> bool:
    return bool(PUBLISH_RE.search(text or ""))


def body_text(command: str, cwd: str | None = None) -> str:
    """Everything the command would publish: inline bodies plus body/input files."""
    parts = []
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    for i, tok in enumerate(tokens):
        if tok in ("--body", "-b", "--title", "-t") and i + 1 < len(tokens):
            parts.append(tokens[i + 1])
        if tok in ("--body-file", "-F", "--input") and i + 1 < len(tokens):
            p = Path(tokens[i + 1])
            if not p.is_absolute() and cwd:
                p = Path(cwd) / p
            try:
                parts.append(p.read_text(errors="replace"))
            except OSError:
                pass
    # a heredoc body passed inline
    if "<<" in command:
        parts.append(command)
    return "\n".join(parts)


def unsourced_claims(text: str) -> list[str]:
    lines = (text or "").splitlines()
    found = []
    for n, line in enumerate(lines):
        for pattern, kind, how in CLAIMS:
            m = pattern.search(line)
            if not m:
                continue
            near = "\n".join(lines[max(0, n - WINDOW): n + WINDOW + 1])
            if EVIDENCE.search(near):
                continue
            found.append(f"  - {kind}: {m.group(0).strip()!r}\n    settle it: {how}")
    return found


def decide(command: str, cwd: str | None = None) -> str | None:
    if not is_publication(command):
        return None
    problems = unsourced_claims(body_text(command, cwd))
    if not problems:
        return None
    return MESSAGE.format(n=len(problems), detail="\n".join(problems))
