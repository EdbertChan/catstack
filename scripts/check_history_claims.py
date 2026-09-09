#!/usr/bin/env python3
"""Flag claims about a repo's own history that were inferred, not queried.

A duration, a count, an authorship, or a never/always about code is answerable
by one git command. Stating one from inference is how a PR body ends up
asserting "five months" when `git log -S` says twenty-four days, "three passes
found this" when one did, and an agent wrote a file a human wrote.

These are the cheapest possible facts to check and the easiest to feel certain
about without checking, which is exactly the combination that ships them.

Usage:  check_history_claims.py <file>...          # or read stdin
Exit 1 when a claim has no adjacent evidence. Read-only.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Each pattern pairs with the command that settles it.
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
     "count", "actually count them: git log --grep=… | wc -l, or grep -c"),
    (re.compile(r"\b(?:written|authored|introduced|added|created)\s+by\b", re.I),
     "authorship", "git log --format='%an <%ae>' -- <path> | sort -u"),
    (re.compile(r"\b(?:never|always)\s+(?:\w+\s+){0,3}"
                r"(?:loaded|ran|run|fired|worked|existed|shipped|merged|landed|applied|called)\b", re.I),
     "never/always", "git log --all -S '<token>' -- <path>"),
    (re.compile(r"\b(?:first|last)\s+(?:introduced|added|appeared|broken|failing)\b", re.I),
     "first/last occurrence", "git log --all -S '<token>' --reverse --format='%ad %h'"),
]

# Evidence that a claim was actually checked, near the claim.
EVIDENCE = re.compile(
    r"```|"                                  # a pasted command or its output
    r"\bgit (?:log|blame|show|rev-list)\b|"  # the query named inline
    r"\b[0-9a-f]{7,40}\b|"                   # a commit sha
    r"\bUNVERIFIED\b",                       # explicitly marked
    re.I,
)
WINDOW = 6  # lines either side


def scan(text: str, label: str) -> list[str]:
    lines = text.splitlines()
    problems = []
    for n, line in enumerate(lines):
        for pattern, kind, how in CLAIMS:
            m = pattern.search(line)
            if not m:
                continue
            near = "\n".join(lines[max(0, n - WINDOW): n + WINDOW + 1])
            if EVIDENCE.search(near):
                continue
            problems.append(
                f"{label}:{n + 1}: {kind} claim with no adjacent evidence\n"
                f"    {m.group(0).strip()!r}\n"
                f"    settle it: {how}\n"
                f"    or write UNVERIFIED: before the claim"
            )
    return problems


def main(argv: list[str]) -> int:
    targets = argv[1:]
    problems: list[str] = []
    if targets:
        for t in targets:
            p = Path(t)
            if p.is_file():
                problems += scan(p.read_text(errors="replace"), p.name)
    else:
        problems += scan(sys.stdin.read(), "stdin")

    if problems:
        print("Claims about repo history that were not queried:\n")
        for p in problems:
            print(p + "\n")
        print("Each of these is one git command. Run it, paste the output, then state the claim.")
        return 1
    print("OK: no unsourced history claims")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
