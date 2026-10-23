#!/usr/bin/env python3
"""Refuse to call a reflect apply finished while one of its worktrees is dirty.

An apply agent that moves its edits to a second worktree can leave the first
one holding the same edits uncommitted. Nothing in the hand-back shows that,
so the parent reports "PR is open" and the user later finds a mixed tree.
This script runs `git status --porcelain` on every reflect worktree and says
so before that report goes out.

Three outcomes, because a path that is not a worktree cannot be called clean:

    clean      every worktree checked has an empty status      exit 0
    dirty      at least one worktree has changes (paths listed) exit 1
    unchecked  at least one path is not a git worktree          exit 2

    python3 reflect_worktrees_clean.py .worktrees/reflect-foo .worktrees/reflect-bar
    python3 reflect_worktrees_clean.py            # every reflect-* worktree of this checkout

A dirty tree is a defect of the apply, not a cleanup chore: the apply agent
parks leftover work by committing it on its own branch, never by discarding.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPTS_DIR, "..", "..", "..", ".."))
CLEAN, DIRTY, UNCHECKED = "clean", "dirty", "unchecked"
EXIT = {CLEAN: 0, DIRTY: 1, UNCHECKED: 2}
WORKTREE_PREFIX = "reflect-"


def _git(path: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", path, *args], capture_output=True, text=True, check=False)


def discover(repo_root: str = REPO_ROOT) -> list[str]:
    """Every linked worktree of repo_root whose directory name starts with reflect-."""
    result = _git(repo_root, "worktree", "list", "--porcelain")
    if result.returncode != 0:
        return []
    found: list[str] = []
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):].strip()
            if os.path.basename(path).startswith(WORKTREE_PREFIX):
                found.append(path)
    return found


def check(path: str) -> tuple[str, list[str]]:
    """(outcome, detail lines) for one path."""
    if not os.path.isdir(path):
        return UNCHECKED, [f"{path} is not a directory"]
    top = _git(path, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        return UNCHECKED, [f"{path} is not inside a git worktree: {top.stderr.strip()}"]
    if os.path.realpath(top.stdout.strip()) != os.path.realpath(path):
        return UNCHECKED, [f"{path} is not a worktree root (toplevel is {top.stdout.strip()})"]
    status = _git(path, "status", "--porcelain")
    if status.returncode != 0:
        return UNCHECKED, [f"git status failed in {path}: {status.stderr.strip()}"]
    lines = [line for line in status.stdout.splitlines() if line.strip()]
    return (DIRTY, lines) if lines else (CLEAN, [])


def verdict(outcomes: list[str]) -> str:
    if UNCHECKED in outcomes:
        return UNCHECKED
    if DIRTY in outcomes:
        return DIRTY
    return CLEAN


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("worktrees", nargs="*", help="worktree paths; default: every reflect-* worktree")
    ap.add_argument("--repo-root", default=REPO_ROOT, help="checkout whose worktrees are listed by default")
    args = ap.parse_args(argv)

    paths = list(args.worktrees) or discover(args.repo_root)
    if not paths:
        print(f"clean\tno {WORKTREE_PREFIX}* worktrees under {args.repo_root}")
        return EXIT[CLEAN]
    outcomes: list[str] = []
    for path in paths:
        outcome, detail = check(path)
        outcomes.append(outcome)
        print(f"{outcome}\t{path}")
        for line in detail:
            print(f"\t{line}")
    final = verdict(outcomes)
    print(f"{final}\t{outcomes.count(DIRTY)} dirty, {outcomes.count(UNCHECKED)} unchecked, {outcomes.count(CLEAN)} clean")
    return EXIT[final]


if __name__ == "__main__":
    sys.exit(main())
