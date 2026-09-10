#!/usr/bin/env python3
"""Flag claims about a repo's own history that were inferred, not queried.

A duration, a count, an authorship, or a never/always about code is answerable
by one git command. Stating one from inference is how a PR body ends up
asserting "five months" when `git log -S` says twenty-four days, "three passes
found this" when one did, and an agent wrote a file a human wrote.

These are the cheapest possible facts to check and the easiest to feel certain
about without checking, which is exactly the combination that ships them.

Usage:  check_history_claims.py FILE...     scan these files
        check_history_claims.py -           read stdin
        check_history_claims.py [--base B]  scan markdown lines this branch
                                            adds vs B (default origin/main)

With no FILE the check never touches stdin: a runner that hands it an open
pipe and never closes it would otherwise block it forever.

Exit 1 when a claim has no adjacent evidence. Exit 2 when the input could not
be read (missing file, unresolvable base): unchecked, never reported as clean.
Read-only.
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
    r"(?<![0-9A-Za-z])(?=[0-9a-f]*[a-f])(?=[0-9a-f]*[0-9])[0-9a-f]{7,40}(?![0-9A-Za-z])|"
    r"\bUNVERIFIED\b",
    re.I,
)
WINDOW = 6

GATE_EXEMPLARS: dict[str, list[str]] = {
    "catch": [
        "this bug has existed for five months",
        "three sessions found this pattern",
        "written by the CI bot",
        "it never fired in production",
        "first introduced after the refactor",
        "this bug has existed for five months 1207349",
    ],
    "allow": [
        "this bug has existed for five months (git log -S 'bug' says a3b4c5d)",
        "UNVERIFIED: three sessions found this pattern",
        "```\nthree sessions found this pattern\n```",
        "this is a normal line with no claims",
        "the function returns a list of strings",
    ],
}


def gate_check(exemplar: str) -> bool:
    return len(scan(exemplar, "test")) > 0


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


def added_markdown(base: str) -> dict[str, str]:
    """Added lines per markdown file in the diff from merge-base(base, HEAD)."""
    mb = subprocess.run(["git", "-C", str(REPO_ROOT), "merge-base", base, "HEAD"], capture_output=True, text=True)
    if mb.returncode != 0:
        raise Unchecked(f"cannot resolve merge-base with {base}: {mb.stderr.strip()}")
    diff = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "diff", "--unified=0", mb.stdout.strip(), "--", "*.md"],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
    )
    if diff.returncode != 0:
        raise Unchecked(f"git diff failed: {diff.stderr.strip()}")
    added: dict[str, list[str]] = {}
    current: str | None = None
    for raw in diff.stdout.splitlines():
        if raw.startswith("+++ "):
            current = raw[6:] if raw.startswith("+++ b/") else None
            continue
        if current is not None and raw.startswith("+"):
            added.setdefault(current, []).append(raw[1:])
    return {path: "\n".join(lines) for path, lines in added.items()}


class Unchecked(Exception):
    pass


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="files to scan; '-' reads stdin")
    ap.add_argument("--base", default="origin/main", help="with no FILE, diff base for added markdown lines")
    args = ap.parse_args(argv[1:])
    problems: list[str] = []
    try:
        if args.files:
            for t in args.files:
                if t == "-":
                    problems += scan(sys.stdin.read(), "stdin")
                    continue
                p = Path(t)
                if not p.is_file():
                    raise Unchecked(f"{t}: not a readable file")
                problems += scan(p.read_text(errors="replace"), p.name)
            scope = f"{len(args.files)} input(s)"
        else:
            added = added_markdown(args.base)
            for path, text in added.items():
                problems += scan(text, path)
            count = sum(len(t.splitlines()) for t in added.values())
            scope = f"{count} added markdown line(s) vs {args.base}"
    except Unchecked as e:
        print(f"unchecked  history claims: {e}", file=sys.stderr)
        return 2

    if problems:
        print("Claims about repo history that were not queried:\n")
        for p in problems:
            print(p + "\n")
        print("Each of these is one git command. Run it, paste the output, then state the claim.")
        return 1
    print(f"OK: no unsourced history claims ({scope})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
