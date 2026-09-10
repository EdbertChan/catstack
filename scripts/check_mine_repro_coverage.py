#!/usr/bin/env python3
"""Session-mine / reflect detector changes need positive + negative repro tests.

Companion to check_hook_test_coverage.py. Hooks with detect.py stay on that
script. This gate covers engine/skills/reflect/scripts detectors that session-mine
and headless reflect rely on: cluster_interventions, dora_ai, and any future
script listed in REQUIRED_PAIRS.

A "positive" test proves the detector fires on the bad / intervention case.
A "negative" test proves it stays silent / incomplete / non-elite on the
clean case. Classification reuses the same name heuristics as the hook
checker so authors do not learn a second vocabulary.

Usage:
    python3 scripts/check_mine_repro_coverage.py
    python3 scripts/check_mine_repro_coverage.py --list
"""
from __future__ import annotations

import ast
import os
import sys
import tempfile

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DETECTORS_DIR = os.path.join(REPO_DIR, "engine", "skills", "reflect", "scripts")
TESTS_DIR = os.path.join(DETECTORS_DIR, "tests")

# script stem -> required test module stem under tests/
REQUIRED_PAIRS = {
    "cluster_interventions": "test_cluster_interventions",
    "dora_ai": "test_dora_ai",
    "session_mine": "test_session_mine",
}

NEGATIVE_RE = (
    "no_hit",
    "not_",
    "does_not",
    "never",
    "silent",
    "incomplete",
    "without_negative",
    "negative",
    "skips",
    "empty",
    "cooldown",
    "blocks",
    "clean",
)
POSITIVE_RE = (
    "hit",
    "fire",
    "trigger",
    "detect",
    "cluster",
    "ready",
    "elite",
    "fail_rate",
    "approval",
    "yes_and_no",
    "complete",
)

PROMISED_CATCH = (
    ("need positive + negative repro tests", None),
    ('A "positive" test proves the detector fires', ("test_stays_silent_when_clean",)),
    ('A "negative" test proves it stays silent', ("test_fires_on_intervention",)),
)
PROMISED_ALLOW = (
    ("need positive + negative repro tests", ("test_fires_on_intervention", "test_stays_silent_when_clean")),
)


def _classify(test_name: str) -> str | None:
    lowered = test_name.lower()
    if any(pat in lowered for pat in NEGATIVE_RE):
        return "negative"
    if any(pat in lowered for pat in POSITIVE_RE):
        return "positive"
    return None


def _test_names(path: str) -> list[str]:
    try:
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
    except (OSError, SyntaxError):
        return []
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
            "test_"
        ):
            names.append(node.name)
    return names


def check_pair(
    script: str, test_stem: str, detectors_dir: str = DETECTORS_DIR, tests_dir: str = TESTS_DIR
) -> list[str]:
    problems: list[str] = []
    script_path = os.path.join(detectors_dir, f"{script}.py")
    test_path = os.path.join(tests_dir, f"{test_stem}.py")
    if not os.path.isfile(script_path):
        problems.append(f"{script}: missing engine/skills/reflect/scripts/{script}.py")
        return problems
    if not os.path.isfile(test_path):
        problems.append(f"{script}: missing {test_stem}.py (need positive + negative tests)")
        return problems
    names = _test_names(test_path)
    classified = {_classify(n) for n in names}
    if "positive" not in classified:
        problems.append(
            f"{script}: no positive test in {test_stem}.py "
            f"(name matching {POSITIVE_RE})"
        )
    if "negative" not in classified:
        problems.append(
            f"{script}: no negative test in {test_stem}.py "
            f"(name matching {NEGATIVE_RE})"
        )
    return problems


def exemplar_flagged(exemplar: tuple[str, ...] | None) -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "demo.py"), "w", encoding="utf-8") as handle:
            handle.write("")
        if exemplar is not None:
            with open(os.path.join(tmp, "test_demo.py"), "w", encoding="utf-8") as handle:
                handle.write("".join(f"def {name}():\n    pass\n" for name in exemplar))
        return bool(check_pair("demo", "test_demo", tmp, tmp))


def main() -> int:
    if "--list" in sys.argv:
        for script, stem in REQUIRED_PAIRS.items():
            print(f"{script} -> tests/{stem}.py")
        return 0
    all_problems: list[str] = []
    for script, stem in REQUIRED_PAIRS.items():
        all_problems.extend(check_pair(script, stem))
    if all_problems:
        print("check_mine_repro_coverage: FAIL")
        for problem in all_problems:
            print(f"  - {problem}")
        return 1
    print(f"check_mine_repro_coverage: OK ({len(REQUIRED_PAIRS)} detector(s) checked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
