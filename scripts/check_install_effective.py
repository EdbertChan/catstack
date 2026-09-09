#!/usr/bin/env python3
"""Verify what is INSTALLED, not what the installer would do.

install.sh's tests all run against a sandboxed fake HOME, which is correct and
is exactly why a real-world drift went unnoticed: $HOME/.claude/CLAUDE.md was a
real file shadowing the symlink, so none of the always-on principles reached
Claude while every install exited 0. A suite that proves the installer works is
not a check that the installation is in effect.

Exits non-zero and names each drift. Read-only.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

def _main_checkout() -> Path:
    """The repo links point at the primary checkout, not at a worktree of it."""
    here = Path(__file__).resolve().parents[1]
    try:
        common = subprocess.run(
            ["git", "-C", str(here), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
        if common:
            return Path(common).parent
    except Exception:
        pass
    return here


REPO = _main_checkout()
HOME = Path(os.environ.get("HOME", Path.home()))
CANARY_PHRASE = "Do not swap in a near-neighbor"


def linked(target: Path, expected: Path) -> str | None:
    if not target.exists() and not target.is_symlink():
        return f"missing: {target}"
    if not target.is_symlink():
        return f"shadowed by a real file, so the repo version is not in effect: {target}"
    resolved = target.resolve()
    if not str(resolved).startswith(str(expected)):
        return f"points outside the repo ({resolved}): {target}"
    return None


def check_links() -> list[str]:
    problems = []
    for target in (
        HOME / ".claude/CLAUDE.md",
        HOME / ".codex/AGENTS.md",
    ):
        if target.exists() or target.is_symlink():
            if (p := linked(target, REPO)) and "AGENTS" not in target.name:
                problems.append(p)
    for skill in (REPO / "corpus/skills").glob("*/SKILL.md"):
        name = skill.parent.name
        installed = HOME / ".claude/skills" / name
        if installed.exists() and not installed.is_symlink():
            problems.append(f"skill shadowed by a real directory: {installed}")
    return problems


def check_hooks_registered() -> list[str]:
    settings = HOME / ".claude/settings.json"
    if not settings.exists():
        return ["no ~/.claude/settings.json; no hook is registered"]
    text = settings.read_text()
    problems = []
    for hook_dir in sorted((REPO / "engine/hooks").glob("*/")):
        if not (hook_dir / "claude.hook.json").exists():
            continue
        if hook_dir.name not in text:
            problems.append(f"hook built but never registered in settings.json: {hook_dir.name}")
    return problems


def check_canary() -> list[str]:
    """Ask the harness itself whether the rules actually loaded."""
    if not (HOME / ".claude/CLAUDE.md").is_symlink():
        return []  # already reported by check_links
    try:
        out = subprocess.run(
            ["claude", "-p", f'Answer with one word only. Do your loaded global '
                              f'instructions contain the exact phrase "{CANARY_PHRASE}"? '
                              f'Answer YES or NO.'],
            capture_output=True, text=True, timeout=120,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return [f"canary could not run ({exc.__class__.__name__}); link state checked only"]
    if "YES" not in out.stdout.upper():
        return [f"canary says the always-on rules are NOT loaded (got {out.stdout.strip()[:60]!r})"]
    return []


def main() -> int:
    problems = check_links() + check_hooks_registered() + check_canary()
    if problems:
        print("Installation is not in effect:")
        for p in problems:
            print(f"  - {p}")
        print("\nRerun `bash install.sh --force` to back up shadowing files and link them.")
        return 1
    print("OK: links resolve into the repo, hooks are registered, canary confirms rules loaded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
