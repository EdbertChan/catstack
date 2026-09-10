#!/usr/bin/env python3
"""Flag claims about a repo's own history that were inferred, not queried.

A duration, a count, an authorship, or a never/always about code is answerable
by one git command. Stating one from inference is how a PR body ends up
asserting "five months" when `git log -S` says twenty-four days, "three passes
found this" when one did, and an agent wrote a file a human wrote.

These are the cheapest possible facts to check and the easiest to feel certain
about without checking, which is exactly the combination that ships them.

Evidence is any of these within six lines of the claim: a fenced code block,
a `git log|blame|show|rev-list` command, `UNVERIFIED`, or a commit SHA -- 7 to
40 lowercase hex characters holding at least one digit and one letter a-f.
An all-digit number such as a ticket or run id is not a SHA and is not
evidence.

Usage:  check_history_claims.py FILE...   (use - for stdin)
Exit 0 when every scanned claim has adjacent evidence.
Exit 1 when a claim has no adjacent evidence.
Exit 2 when a FILE cannot be read: an unreadable input is unchecked, not clean.
With no FILE it scans nothing, prints UNCHECKED, and exits 0 (fails open).
It never reads stdin unless asked with -, so a runner that leaves stdin open
cannot hang it. Read-only.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

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

EVIDENCE = re.compile(
    r"```|"
    r"\bgit (?:log|blame|show|rev-list)\b|"
    r"\b(?-i:(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40})\b|"
    r"\bUNVERIFIED\b",
    re.I,
)
WINDOW = 6

PROMISED_CATCH = (
    "This retry loop has been broken for five months.",
    "Three passes found this bug.",
    "This file was written by an agent.",
    "The hook never fired in production.",
    "Tracked as ticket 4417302.\nThis retry loop has been broken for five months.",
    "Reverted in DEADBEEF1 after being broken for five months.",
    "The page was defaced after being broken for five months.",
)
PROMISED_ALLOW = (
    "`git log -S retry` dates it: broken for five months.",
    "Introduced in 3f9a2c1, so broken for five months.",
    "UNVERIFIED: this retry loop has been broken for five months.",
    "The retry loop backs off exponentially.",
)


def flags_exemplar(exemplar: str) -> bool:
    return bool(scan(exemplar, "exemplar"))


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
    if not targets:
        print("UNCHECKED: no FILE given, nothing scanned (pass FILE... or - for stdin)")
        return 0
    problems: list[str] = []
    for t in targets:
        if t == "-":
            problems += scan(sys.stdin.read(), "stdin")
            continue
        p = Path(t)
        if not p.is_file():
            print(f"UNCHECKED: {t}: not a readable file", file=sys.stderr)
            return 2
        problems += scan(p.read_text(errors="replace"), p.name)

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
