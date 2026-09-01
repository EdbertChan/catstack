#!/usr/bin/env python3
"""Fail when a change codifies a new rule in prose with no code enforcing it.

thrash-reflect-automate step 3 is "codify the invariant in the skill"; step 2
is "fix the class of bug in code". Landing 3 without 2 is invisible drift: a
documented invariant nothing enforces until the next validation run happens
to catch it (see principle-assert-invariants-not-last-bug). This script is
the mechanical check: if the diff ADDS rule-shaped prose lines (MUST, never,
do not, always, gate, invariant, block) to skill/rule markdown and touches no
code file at all, exit 1.

    python3 scripts/check_codify_has_code.py                # diff vs origin/main
    python3 scripts/check_codify_has_code.py --base main
    python3 scripts/check_codify_has_code.py --allow-prose-only   # doc-only PR, explicit

Exit 0: no new rule prose, or code changed alongside it, or --allow-prose-only.
Exit 1: new rule prose with no code change.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

PROSE_PREFIXES = ("engine/skills/", "corpus/skills/", "product/skills/", "always-on/", "cursor/", "commands/")
PROSE_FILES = ("CLAUDE.md", "AGENTS.md")
CODE_SUFFIXES = (".py", ".mjs", ".js", ".ts", ".sh", ".json", ".yaml", ".yml", ".toml")

RULE_RE = re.compile(
    r"\b(?:MUST(?: NOT)?|never|do(?:es)? not|don't|cannot|always|only|required|"
    r"is not (?:enough|sufficient|proof)|fail(?:s)? closed|gate|invariant|block(?:s|ed)?|exit 2)\b",
    re.IGNORECASE,
)


def is_prose(path: str) -> bool:
    if "/tests/" in "/" + path:
        return False
    return path.endswith(".md") and (path.startswith(PROSE_PREFIXES) or path in PROSE_FILES)


def is_code(path: str) -> bool:
    return path.endswith(CODE_SUFFIXES) or path == "install.sh"


def added_rule_lines(diff_text: str) -> list[tuple[str, str]]:
    """(path, line) for each added line in a prose file that looks like a rule."""
    out: list[tuple[str, str]] = []
    current: str | None = None
    for raw in diff_text.splitlines():
        if raw.startswith("+++ b/"):
            current = raw[6:]
            continue
        if raw.startswith("+++ ") or raw.startswith("--- "):
            current = None
            continue
        if current is None or not raw.startswith("+") or raw.startswith("+++"):
            continue
        line = raw[1:].strip()
        if is_prose(current) and line and not line.startswith(("#", "```")) and RULE_RE.search(line):
            out.append((current, line))
    return out


def check(diff_text: str, changed_paths: list[str]) -> list[str]:
    rules = added_rule_lines(diff_text)
    if not rules:
        return []
    if any(is_code(p) for p in changed_paths):
        return []
    lines = [f"{p}: + {l[:100]}" for p, l in rules[:8]]
    return ["new rule prose with no code change (thrash-reflect-automate step 3 without step 2):"] + lines


def git_diff(base: str) -> tuple[str, list[str]]:
    mb = subprocess.run(["git", "-C", str(REPO_ROOT), "merge-base", base, "HEAD"], capture_output=True, text=True)
    if mb.returncode != 0:
        raise SystemExit(f"fail  cannot resolve merge-base with {base}: {mb.stderr.strip()}")
    ref = mb.stdout.strip()
    diff = subprocess.run(["git", "-C", str(REPO_ROOT), "diff", ref], capture_output=True, text=True, check=True).stdout
    names = subprocess.run(["git", "-C", str(REPO_ROOT), "diff", "--name-only", ref], capture_output=True, text=True, check=True).stdout
    return diff, [n for n in names.splitlines() if n.strip()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--allow-prose-only", action="store_true", help="explicitly accept a docs-only change")
    args = ap.parse_args(argv)
    diff, paths = git_diff(args.base)
    problems = check(diff, paths)
    if problems and args.allow_prose_only:
        print("ok      codify-has-code: prose-only change explicitly allowed (--allow-prose-only)")
        return 0
    if problems:
        for p in problems:
            print("fail  " + p, file=sys.stderr)
        return 1
    print("ok      codify-has-code")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
