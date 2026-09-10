#!/usr/bin/env python3
"""Flag claims about a repo's own history that were inferred, not queried.

A duration, a count, an authorship, or a never/always about code is answerable
by one git command. Stating one from inference is how a PR body ends up
asserting "five months" when `git log -S` says twenty-four days, "three passes
found this" when one did, and an agent wrote a file a human wrote.

These are the cheapest possible facts to check and the easiest to feel certain
about without checking, which is exactly the combination that ships them.

Usage:  check_history_claims.py [--base REF] [FILE... | -]
With no FILE it scans this branch's commit messages since the merge-base with
--base (default origin/main); `-` reads stdin. It never waits on stdin unasked.

Exit 0: no unsourced claim. Exit 1: a claim has no adjacent evidence.
Exit 2: unchecked, because a FILE is not a readable file or the base does not
resolve; nothing was read, so nothing is reported clean. Read-only.

Adjacent evidence, within six lines of the claim, is a code fence, a
`git log`/`blame`/`show`/`rev-list` command, UNVERIFIED, or a commit SHA. A
commit SHA is 7-40 lowercase hex holding both a digit and a letter, so a
decimal id (a ticket or row number) or an all-letter hex word ("defaced") is
not evidence.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

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
    r"(?-i:\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b)|"
    r"\bUNVERIFIED\b",
    re.I,
)
WINDOW = 6

PROMISED_CATCH = (
    ("A duration", "This hook ran for five months before anyone noticed."),
    ("a count", "Three review passes found this bug."),
    ("an authorship", "The detector was written by an agent."),
    ("a never/always about code", "The hook never fired in CI."),
    ("a decimal id (a ticket or row number)", "This hook ran for five months.\nSee ticket 1207349."),
    ('an all-letter hex word ("defaced") is not evidence', "The hook never fired after the defaced config."),
    ("7-40 lowercase hex", "This hook ran for five months.\nSee build DEADBEEF1."),
)
PROMISED_ALLOW = (
    ("UNVERIFIED", "UNVERIFIED: this hook ran for five months."),
    ("`git log`/`blame`/`show`/`rev-list` command", "This hook ran for five months.\n    git log -S hook --format='%ad %h' --date=short"),
    ("a code fence", "This hook ran for five months:\n```\n3 commits\n```"),
    ("holding both a digit and a letter", "This hook ran for five months.\nIntroduced in 3f9e2a1c."),
    ("Flag claims about a repo's own history", "The hook blocks a merge that has no test."),
)


def exemplar_flagged(exemplar: str) -> bool:
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


class Unchecked(Exception):
    pass


def branch_commit_messages(base: str) -> str:
    mb = subprocess.run(["git", "-C", str(REPO_ROOT), "merge-base", base, "HEAD"], capture_output=True, text=True)
    if mb.returncode != 0:
        raise Unchecked(f"cannot resolve merge-base with {base}: {mb.stderr.strip()}")
    log = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "log", "--format=%B", f"{mb.stdout.strip()}..HEAD"],
        capture_output=True, text=True,
    )
    if log.returncode != 0:
        raise Unchecked(f"cannot read commit messages since {base}: {log.stderr.strip()}")
    return log.stdout


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("targets", nargs="*", help="files to scan, or - for stdin")
    ap.add_argument("--base", default="origin/main", help="with no targets, scan commit messages since this ref")
    args = ap.parse_args(argv[1:])
    problems: list[str] = []
    try:
        if not args.targets:
            problems += scan(branch_commit_messages(args.base), f"commits since {args.base}")
        for t in args.targets:
            if t == "-":
                problems += scan(sys.stdin.read(), "stdin")
                continue
            p = Path(t)
            if not p.is_file():
                raise Unchecked(f"{t} is not a readable file")
            problems += scan(p.read_text(errors="replace"), p.name)
    except Unchecked as exc:
        print(f"UNCHECKED: {exc}", file=sys.stderr)
        return 2

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
