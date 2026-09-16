#!/usr/bin/env python3
"""The learned rule for finishing a merge or rebase.

Two premise tests use real git. In the first, both branches change line 1 and
only the current branch also changes line 5; `git checkout --theirs` resolves
the conflict and silently drops the line-5 change, which never conflicted. In
the second, git merges two branches with no conflict at all, yet the result
fails the test one branch's commit declared. Both losses are what the rule's
three-way reconciliation of declared intent, code, and result exists to catch.
"""
import os
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEARNED = os.path.join(REPO_ROOT, "corpus", "CLAUDE.learned.md")
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "test"))

from git_test_repo import init_repo  # noqa: E402

BASE_LINES = ["one", "two", "three", "four", "five"]


def git(root, *args, check=True):
    return subprocess.run(
        ["git", "-C", root, "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        capture_output=True, text=True, check=check,
    )


def write_lines(root, lines):
    with open(os.path.join(root, "notes.txt"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def read_lines(root):
    with open(os.path.join(root, "notes.txt"), encoding="utf-8") as handle:
        return handle.read().splitlines()


def working_style_section():
    with open(LEARNED, encoding="utf-8") as handle:
        text = handle.read()
    start = text.index("# Working style")
    end = text.find("\n# ", start + 1)
    return text[start:] if end == -1 else text[start:end]


class TestTakingTheirsDropsNonConflictingChanges(unittest.TestCase):
    def test_checkout_theirs_loses_the_current_branch_line_five_change(self):
        with tempfile.TemporaryDirectory() as root:
            init_repo(root, "-b", "main")
            write_lines(root, BASE_LINES)
            git(root, "add", "notes.txt")
            git(root, "commit", "-qm", "base")
            git(root, "checkout", "-qb", "other")
            write_lines(root, ["one-other"] + BASE_LINES[1:])
            git(root, "commit", "-qam", "other edits line 1")
            git(root, "checkout", "-q", "main")
            write_lines(root, ["one-main", "two", "three", "four", "five-main"])
            git(root, "commit", "-qam", "main edits lines 1 and 5")

            merge = git(root, "merge", "other", check=False)
            self.assertNotEqual(merge.returncode, 0, "the setup must produce a conflict")
            git(root, "checkout", "--theirs", "notes.txt")

            resolved = read_lines(root)
            self.assertEqual(resolved[0], "one-other")
            self.assertEqual(resolved[4], "five", "taking theirs reverted main's non-conflicting line 5")


CALC_BASE = [
    "def total(items):",
    "    return sum(items)",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
]


def write_file(root, name, lines):
    with open(os.path.join(root, name), "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


class TestCleanMergeCanBreakDeclaredIntent(unittest.TestCase):
    def test_textually_clean_merge_fails_the_test_one_side_declared(self):
        with tempfile.TemporaryDirectory() as root:
            init_repo(root, "-b", "main")
            write_file(root, "calc.py", CALC_BASE)
            git(root, "add", "calc.py")
            git(root, "commit", "-qm", "base")

            git(root, "checkout", "-qb", "skip-negatives")
            write_file(root, "calc.py", ["def total(items):", "    return sum(i for i in items if i >= 0)"] + CALC_BASE[2:])
            write_file(root, "test_calc.py", [
                "import unittest",
                "from calc import total",
                "",
                "",
                "class T(unittest.TestCase):",
                "    def test_negatives_are_ignored(self):",
                "        self.assertEqual(total([2, -5]), 2)",
            ])
            git(root, "add", "calc.py", "test_calc.py")
            git(root, "commit", "-qm", "total ignores negative items\n\nTest: test_calc.test_negatives_are_ignored")

            git(root, "checkout", "-q", "main")
            write_file(root, "calc.py", CALC_BASE[:-1] + ["total = lambda items: sum(items)"])
            git(root, "commit", "-qam", "expose total as a lambda")

            merge = git(root, "merge", "--no-edit", "skip-negatives", check=False)
            self.assertEqual(merge.returncode, 0, merge.stdout + merge.stderr)

            declared = git(root, "log", "-1", "--format=%B", "skip-negatives").stdout
            self.assertIn("test_calc.test_negatives_are_ignored", declared)
            run = subprocess.run(
                [sys.executable, "-m", "unittest", "test_calc"],
                cwd=root, capture_output=True, text=True,
            )
            self.assertNotEqual(run.returncode, 0, "the clean merge was expected to break the declared test")
            self.assertIn("FAILED", run.stderr)


class TestConflictReconcileRule(unittest.TestCase):
    PREFIX = "- When finishing a merge or rebase"

    def rule(self):
        for line in working_style_section().splitlines():
            if line.startswith(self.PREFIX):
                return line
        raise AssertionError("the conflict-resolution rule is missing")

    def test_rule_forbids_taking_a_whole_side(self):
        rule = self.rule()
        self.assertIn("Never take one side's whole file", rule)
        self.assertIn("`git checkout --theirs`", rule)

    def test_rule_reconciles_declared_intent_code_and_result(self):
        rule = self.rule()
        self.assertIn("commit messages and PR description", rule)
        self.assertIn("what each side's code actually does", rule)
        self.assertIn("what the resolved result does", rule)
        self.assertIn("`git diff <base> -- <file>`", rule)
        self.assertIn("every test either side named still passes", rule)

    def test_rule_checks_clean_merges_too(self):
        self.assertIn("a clean merge is checked the same way", self.rule())

    def test_rule_flags_mismatch_with_history_and_evidence(self):
        rule = self.rule()
        self.assertIn("stop and flag it to me instead of choosing", rule)
        self.assertIn("run `why` on the conflicting lines", rule)
        self.assertIn("`principle-prove-it`", rule)
        self.assertIn("pastes the failing test output", rule)

    def test_rule_names_its_source(self):
        self.assertIn("https://doi.org/10.1145/2025113.2025139", self.rule())


if __name__ == "__main__":
    unittest.main()
