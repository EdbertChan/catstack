#!/usr/bin/env python3
"""Every engine/hooks/<name>/ with a detect.py must have a tests/ dir containing at
least one positive test (proves the detector fires on the bad case it
exists to catch) and at least one negative test (proves it stays silent on
a clean case). This only checks that both shapes of test exist by name --
it cannot judge whether a test actually reproduces the right scenario. That
judgment is still the author's.

A detect.py that opens, reads, or sizes a file also needs a test named for
the input it could not read (unreadable, too_large, fails_open, missing, ...),
so an unchecked file cannot pass as clean.

Usage:
    python3 scripts/check_hook_test_coverage.py            # check every hook
    python3 scripts/check_hook_test_coverage.py engine/hooks/foo   # check one hook
"""
from __future__ import annotations

import ast
import os
import sys
import tempfile

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

PROMISED_CATCH = (
    "inline-input",
    "inline-input test_fires_on_bad_case",
    "inline-input test_stays_silent_on_clean_case",
    "reads-files test_fires_on_bad_case test_stays_silent_on_clean_case",
)
PROMISED_ALLOW = (
    "inline-input test_fires_on_bad_case test_stays_silent_on_clean_case",
    "reads-files test_fires_on_bad_case test_stays_silent_on_clean_case test_unreadable_file_fails_open",
)


def flags_exemplar(exemplar: str) -> bool:
    kind, *names = exemplar.split()
    detector = "text = open(path).read()\n" if kind == "reads-files" else "def decide(text):\n    return None\n"
    with tempfile.TemporaryDirectory() as tmp:
        hook_dir = os.path.join(tmp, "demo")
        os.makedirs(hook_dir)
        with open(os.path.join(hook_dir, "detect.py"), "w", encoding="utf-8") as handle:
            handle.write(detector)
        if names:
            os.makedirs(os.path.join(hook_dir, "tests"))
            with open(os.path.join(hook_dir, "tests", "test_demo.py"), "w", encoding="utf-8") as handle:
                handle.write("".join(f"def {name}():\n    pass\n" for name in names))
        return bool(check_hook(hook_dir))


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


def _parse_python_files(folder: str, skip_tests: bool) -> tuple[list[ast.AST], list[str]]:
    trees: list[ast.AST] = []
    unreadable: list[str] = []
    for root, dirs, files in os.walk(folder):
        if skip_tests:
            dirs[:] = [directory for directory in dirs if directory != "tests"]
        for filename in sorted(files):
            if not filename.endswith(".py"):
                continue
            path = os.path.join(root, filename)
            try:
                with open(path, encoding="utf-8") as handle:
                    trees.append(ast.parse(handle.read(), filename=path))
            except (OSError, SyntaxError, UnicodeDecodeError) as error:
                unreadable.append(f"{path} ({type(error).__name__}: {error})")
    return trees, unreadable


def _imports_judge(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
            alias.name == "judge" or alias.name.endswith(".judge") for alias in node.names
        ):
            return True
        if isinstance(node, ast.ImportFrom) and node.module and (
            node.module == "judge" or node.module.endswith(".judge")
        ):
            return True
    return False


def _uses_judge_test_base(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and any(alias.name == "JudgeTestCase" for alias in node.names):
            return True
        if isinstance(node, ast.ClassDef) and any(
            (isinstance(base, ast.Name) and base.id == "JudgeTestCase")
            or (isinstance(base, ast.Attribute) and base.attr == "JudgeTestCase")
            for base in node.bases
        ):
            return True
    return False


def judge_isolation_problems(hook_dir: str) -> list[str]:
    name = os.path.basename(hook_dir)
    sources, unreadable = _parse_python_files(hook_dir, skip_tests=True)
    problems = [f"{name}: could not read {path}, so its judge imports are unchecked" for path in unreadable]
    if not any(_imports_judge(tree) for tree in sources):
        return problems
    tests_dir = os.path.join(hook_dir, "tests")
    if not os.path.isdir(tests_dir):
        return problems + [f"{name}: imports llm-judge but has no tests/ dir using JudgeTestCase"]
    tests, unreadable_tests = _parse_python_files(tests_dir, skip_tests=False)
    problems += [f"{name}: could not read {path}, so its JudgeTestCase use is unchecked" for path in unreadable_tests]
    if not any(_uses_judge_test_base(tree) for tree in tests):
        problems.append(f"{name}: imports llm-judge but no test imports or subclasses JudgeTestCase")
    return problems


def hook_dirs() -> list[str]:
    if not os.path.isdir(HOOKS_DIR):
        raise FileNotFoundError(f"hooks folder not found, so no hook's judge isolation was checked: {HOOKS_DIR}")
    return [
        os.path.join(HOOKS_DIR, name)
        for name in sorted(os.listdir(HOOKS_DIR))
        if os.path.isdir(os.path.join(HOOKS_DIR, name))
    ]


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
        if os.path.isfile(os.path.join(hook_dir, "detect.py")):
            all_problems.extend(check_hook(hook_dir))
    for hook_dir in [os.path.abspath(a) for a in args] if args else hook_dirs():
        all_problems.extend(judge_isolation_problems(hook_dir))

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
