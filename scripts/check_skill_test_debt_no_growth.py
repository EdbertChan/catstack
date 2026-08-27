#!/usr/bin/env python3
"""scripts/skill_test_debt_allowlist.txt MUST be shrink-only.

Companion to check_skill_test_coverage.py. A skill can graduate off the
allowlist (remove a line) once it has real coverage, but nothing may add a
new line -- every new or newly-touched skill must ship coverage instead of
grandfathering itself in.

Diffs the allowlist file against a base ref (GITHUB_BASE_REF in a GitHub
Actions PR, else --base, else origin/main) and fails if any line was
added. Fails OPEN (prints a warning, exits 0) when no base ref is
resolvable at all -- e.g. a shallow local clone with no remote -- since
this is a secondary safety net, not the primary gate
(check_skill_test_coverage.py already fails closed on real missing
coverage).

Usage:
    python3 scripts/check_skill_test_debt_no_growth.py
    python3 scripts/check_skill_test_debt_no_growth.py --base origin/main
"""
from __future__ import annotations

import os
import subprocess
import sys

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALLOWLIST_REL = "scripts/skill_test_debt_allowlist.txt"


def _run(args: list[str], cwd: str = REPO_DIR) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def resolve_base(explicit: str | None, cwd: str = REPO_DIR) -> str | None:
    if explicit:
        candidates = [explicit]
    else:
        base_branch = os.environ.get("GITHUB_BASE_REF")
        candidates = [f"origin/{base_branch}"] if base_branch else ["origin/main"]

    for ref in candidates:
        if _run(["git", "rev-parse", "--verify", ref], cwd=cwd).returncode == 0:
            return ref

    # Not resolvable locally -- try a shallow fetch before giving up.
    fetch_name = os.environ.get("GITHUB_BASE_REF", "main")
    _run(["git", "fetch", "--depth=1", "origin", fetch_name], cwd=cwd)
    ref = f"origin/{fetch_name}"
    if _run(["git", "rev-parse", "--verify", ref], cwd=cwd).returncode == 0:
        return ref
    return None


def added_lines(base_ref: str, cwd: str = REPO_DIR) -> list[str] | None:
    result = _run(["git", "diff", f"{base_ref}...HEAD", "--", ALLOWLIST_REL], cwd=cwd)
    if result.returncode != 0:
        return None
    added = []
    for line in result.stdout.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        text = line[1:].strip()
        if text and not text.startswith("#"):
            added.append(text)
    return added


def main() -> int:
    explicit = None
    args = sys.argv[1:]
    if args and args[0] == "--base" and len(args) > 1:
        explicit = args[1]

    base_ref = resolve_base(explicit)
    if base_ref is None:
        print(
            "warn  skill_test_debt_allowlist.txt: no base ref resolvable, "
            "skipping growth check",
            file=sys.stderr,
        )
        return 0

    added = added_lines(base_ref)
    if added is None:
        print(
            f"warn  skill_test_debt_allowlist.txt: could not diff against {base_ref}, "
            "skipping growth check",
            file=sys.stderr,
        )
        return 0

    if added:
        print(
            f"fail  {ALLOWLIST_REL} grew relative to {base_ref} -- new skills "
            "must ship real coverage, not grandfather in:",
            file=sys.stderr,
        )
        for entry in added:
            print(f"  + {entry}", file=sys.stderr)
        return 1

    print("ok      skill test debt allowlist did not grow")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
