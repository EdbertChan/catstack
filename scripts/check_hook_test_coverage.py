#!/usr/bin/env python3
"""Every engine/hooks/<name>/ with a detect.py must have a tests/ dir containing at
least one positive test (proves the detector fires on the bad case it
exists to catch) and at least one negative test (proves it stays silent on
a clean case). This only checks that both shapes of test exist by name --
it cannot judge whether a test actually reproduces the right scenario. That
judgment is still the author's.

Usage:
    python3 scripts/check_hook_test_coverage.py            # check every hook
    python3 scripts/check_hook_test_coverage.py engine/hooks/foo   # check one hook
"""
from __future__ import annotations

import ast
import os
import sys

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS_DIR = os.path.join(REPO_DIR, "engine", "hooks")

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
UNCHECKED_RE = (
    "unscannable",
    "unchecked",
    "unreadable",
    "too_large",
    "over_ceiling",
    "refus",
    "cannot_check",
    "could_not_read",
    "fails_open",
    "fail_open",
    "missing",
    "nonexistent",
    "no_transcript",
    "garbage",
    "corrupt",
    "malformed",
)
READS_INPUT_RE = (
    "open(",
    "read(",
    "getsize",
    "st_size",
    "isfile",
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


def reads_external_input(detector_path: str) -> bool:
    """True when a detector opens or sizes a file it did not receive inline.

    Such a detector has a third outcome besides hit and clean: input it could
    not read. That outcome has to be pinned by a test, whichever way the hook
    resolves it, so it cannot silently collapse into clean.
    """
    try:
        with open(detector_path, encoding="utf-8") as handle:
            source = handle.read()
    except OSError:
        return False
    return any(token in source for token in READS_INPUT_RE)


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
    detector = os.path.join(hook_dir, "detect.py")
    if reads_external_input(detector) and not any(
        pat in n.lower() for n in names for pat in UNCHECKED_RE
    ):
        problems.append(
            f"{name}: detect.py reads files but no test pins its behavior on input it "
            "could not read (name it for the unreadable case: unscannable, unreadable, "
            "too_large, refuses, fails_open, missing, malformed). Fail open or fail "
            "closed is the hook's own documented choice; leaving it untested, so an "
            "unchecked file passes as clean, is not."
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
