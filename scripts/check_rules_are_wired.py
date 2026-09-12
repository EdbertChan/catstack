#!/usr/bin/env python3
"""Every phrase checker must be reachable from code, or say why it is not.

A rule that exists but nothing calls is worse than a missing rule: it reads as
covered in review and never fires in practice. Five `plain-words-*` checkers --
including the one banning jargon -- shipped with no caller at all, so the rule
was written five ways and enforced zero.

Wired means some non-test source file under engine/ names the checker. The only
other acceptable state is an explicit `unwired_reason` in the phrase file, which
mirrors this repo's existing `subagent_stop.inherit: false` + `reason` pattern:
an opt-out has to be stated, not inferred from silence.

Fail-safe defaults, Saltzer & Schroeder 1975:
https://web.mit.edu/Saltzer/www/publications/protection/Basic.html -- absence of
a caller is a deny, never a pass.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS_ROOT = os.path.join(REPO_ROOT, "engine", "hooks")
SOURCE_SUFFIXES = (".py", ".sh", ".mjs", ".cjs", ".js", ".json")


def phrase_files() -> list[str]:
    found = []
    for hook in sorted(os.listdir(HOOKS_ROOT)):
        phrases_dir = os.path.join(HOOKS_ROOT, hook, "phrases")
        if not os.path.isdir(phrases_dir):
            continue
        for name in sorted(os.listdir(phrases_dir)):
            if name.endswith(".json"):
                found.append(os.path.join(phrases_dir, name))
    return found


def checker_name(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"check_rules_are_wired: cannot read {path}: {exc}", file=sys.stderr)
        return None
    name = data.get("checker")
    return name if isinstance(name, str) and name else None


def unwired_reason(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    reason = data.get("unwired_reason")
    return reason.strip() if isinstance(reason, str) and reason.strip() else None


def callers(name: str) -> list[str]:
    """Non-test source files under engine/ that name this checker.

    The name must appear quoted. A bare substring match passes a dormant
    checker whose name is an ordinary word: `example` matched three files that
    merely used the word in prose.
    """
    pattern = f"[\"']{name}[\"']"
    try:
        result = subprocess.run(
            ["grep", "-rlE", "--include=*.py", "--include=*.sh", "--include=*.mjs",
             "--include=*.js", "--include=*.json", pattern, HOOKS_ROOT],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"check_rules_are_wired: grep failed: {exc}") from exc

    hits = []
    for line in result.stdout.splitlines():
        path = line.strip()
        if not path:
            continue
        parts = path.split(os.sep)
        if "phrases" in parts or "tests" in parts or "__pycache__" in parts:
            continue
        if path.endswith(SOURCE_SUFFIXES):
            hits.append(os.path.relpath(path, REPO_ROOT))
    return hits


def main() -> int:
    problems = []
    checked = 0
    for path in phrase_files():
        relative = os.path.relpath(path, REPO_ROOT)
        name = checker_name(path)
        if not name:
            problems.append(f"{relative}: no `checker` name, so nothing can call it")
            continue
        checked += 1
        found = callers(name)
        if found:
            continue
        reason = unwired_reason(path)
        if reason:
            print(f"opt-out {name}: {reason}")
            continue
        problems.append(
            f"{relative}: checker `{name}` has no caller under engine/ outside phrases/ "
            "and tests/. Wire it, or add an `unwired_reason` saying why it ships dormant.")

    if problems:
        print("check_rules_are_wired: FAIL", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"check_rules_are_wired: OK ({checked} checker(s) checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
