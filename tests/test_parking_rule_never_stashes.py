#!/usr/bin/env python3
"""Parking abandoned work must never mean `git stash` in an always-loaded rule.

cat-mode forbids stashing the primary checkout, because another session or
agent may be writing to it; a stash there takes their edits too. The learned
Session hygiene rule once told the agent to park with `git stash push`, so the
two always-loaded surfaces disagreed and the agent could follow either.
"""
import glob
import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEARNED = os.path.join(REPO_ROOT, "corpus", "CLAUDE.learned.md")


def always_loaded_surfaces():
    patterns = [
        "engine/CLAUDE.core.md",
        "corpus/CLAUDE.learned.md",
        "corpus/skills/cat-mode/SKILL.md",
        "corpus/skills/cat-mode/references/*.md",
        "always-on/*.md",
        "cursor/rules/*.mdc",
    ]
    paths = []
    for pattern in patterns:
        paths.extend(sorted(glob.glob(os.path.join(REPO_ROOT, pattern))))
    return paths


def session_hygiene_section():
    with open(LEARNED, encoding="utf-8") as handle:
        text = handle.read()
    start = text.index("# Session hygiene")
    end = text.index("\n# ", start + 1)
    return text[start:end]


class TestParkingRuleNeverStashes(unittest.TestCase):
    def test_surfaces_exist(self):
        self.assertGreaterEqual(len(always_loaded_surfaces()), 3)

    def test_no_always_loaded_rule_recommends_git_stash_push(self):
        for path in always_loaded_surfaces():
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            with self.subTest(path=os.path.relpath(path, REPO_ROOT)):
                self.assertNotIn("git stash push", text)

    def test_session_hygiene_parks_on_a_branch_or_worktree(self):
        section = session_hygiene_section()
        self.assertIn("WIP branch", section)
        self.assertIn("worktree", section)
        self.assertIn("never `git stash`", section)


if __name__ == "__main__":
    unittest.main()
