#!/usr/bin/env python3
"""Every hooks/<name>/ with a detect.py must have a tests/ dir containing at
least one positive test (proves the detector fires on the bad case it
exists to catch) and at least one negative test (proves it stays silent on
a clean case). This only checks that both shapes of test exist by name --
it cannot judge whether a test actually reproduces the right scenario. That
judgment is still the author's.

Usage:
    python3 scripts/check_hook_test_coverage.py            # check every hook
    python3 scripts/check_hook_test_coverage.py hooks/foo   # check one hook
"""
from __future__ import annotations

import ast
import os
import sys

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS_DIR = os.path.join(REPO_DIR, "hooks")

# Checked in this order -- "no_hit" must classify as negative before the
# "hit" positive pattern below gets a chance to match its substring.
NEGATIVE_RE = (
    "no_hit",
    "not_",
    "does_not",
    "never",
    "silent",
    "allow",
    "calm",
    "fails_open",
    "fail_open",
    "passes",
    "prints_nothing",
    "is_ignored",
    "unrelated",
    "clean",
    "empty",
)
POSITIVE_RE = (
    "hit",
    "fire",
    "trigger",
    "block",
    "flag",
    "detect",
    "thrash",
    "leak",
    "risk",
    "deny",
    "violat",
)


def _classify(test_name: str) -> str | None:
    lowered = test_name.lower()
    if any(pat in lowered for pat in NEGATIVE_RE):
        return "negative"
    if any(pat in lowered for pat in POSITIVE_RE):
        return "positive"
    return None


def _test_names(tests_dir: str) -> list[str]:
    names: list[str] = []
    for fname in sorted(os.listdir(tests_dir)):
        if not (fname.startswith("test_") and fname.endswith(".py")):
            continue
        path = os.path.join(tests_dir, fname)
        try:
            with open(path, encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=path)
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                names.append(node.name)
    return names


def hooks_with_detector() -> list[str]:
    if not os.path.isdir(HOOKS_DIR):
        return []
    found = []
    for name in sorted(os.listdir(HOOKS_DIR)):
        hook_dir = os.path.join(HOOKS_DIR, name)
        if os.path.isfile(os.path.join(hook_dir, "detect.py")):
            found.append(hook_dir)
    return found


def check_hook(hook_dir: str) -> list[str]:
    """Return a list of problems for this hook, empty if it passes."""
    name = os.path.basename(hook_dir)
    tests_dir = os.path.join(hook_dir, "tests")
    if not os.path.isdir(tests_dir):
        return [f"{name}: has detect.py but no tests/ dir"]
    names = _test_names(tests_dir)
    classified = {_classify(n) for n in names}
    problems = []
    if "positive" not in classified:
        problems.append(
            f"{name}: no positive test found (a test name matching {POSITIVE_RE} "
            "that proves the detector fires on the bad case)"
        )
    if "negative" not in classified:
        problems.append(
            f"{name}: no negative test found (a test name matching {NEGATIVE_RE} "
            "that proves the detector stays silent on a clean case)"
        )
    return problems


def main() -> int:
    args = sys.argv[1:]
    if args:
        targets = [os.path.abspath(a) for a in args]
    else:
        targets = hooks_with_detector()

    all_problems: list[str] = []
    for hook_dir in targets:
        if not os.path.isfile(os.path.join(hook_dir, "detect.py")):
            continue
        all_problems.extend(check_hook(hook_dir))

    if all_problems:
        print("check_hook_test_coverage: FAIL")
        for problem in all_problems:
            print(f"  - {problem}")
        return 1

    checked = len(targets) if args else len(hooks_with_detector())
    print(f"check_hook_test_coverage: OK ({checked} hook(s) checked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
