#!/usr/bin/env python3
"""The learned rule against resolving a conflict by taking one side's file.

The premise test builds a real conflict: both branches change line 1, and only
the current branch also changes line 5. `git checkout --theirs` resolves the
conflict and silently drops the line-5 change, which never conflicted. That
is the loss the rule exists to prevent.
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


class TestConflictWholeSideRule(unittest.TestCase):
    PREFIX = "- When resolving a merge or rebase conflict"

    def rule(self):
        for line in working_style_section().splitlines():
            if line.startswith(self.PREFIX):
                return line
        raise AssertionError("the conflict-resolution rule is missing")

    def test_rule_forbids_taking_a_whole_side(self):
        rule = self.rule()
        self.assertIn("never take one side's whole file", rule)
        self.assertIn("`git checkout --theirs`", rule)

    def test_rule_requires_a_three_way_merge_and_a_diff_check(self):
        rule = self.rule()
        self.assertIn("three-way merge", rule)
        self.assertIn("`git diff <base> -- <file>`", rule)


if __name__ == "__main__":
    unittest.main()
