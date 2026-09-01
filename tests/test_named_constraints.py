#!/usr/bin/env python3
"""Structural tests for the three-harness always-on named constraints."""

import os
import re
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SURFACES = {
    "Codex": os.path.join(REPO_ROOT, "always-on", "named-constraints.md"),
    "Claude": os.path.join(REPO_ROOT, "CLAUDE.md"),
    "Cursor": os.path.join(REPO_ROOT, "cursor", "rules", "named-constraints.mdc"),
}

PERSISTENCE_RULE = (
    "After direction is set, keep taking the next safe, in-scope step until "
    "the requested outcome is complete."
)
NO_PERMISSION_PAUSE = "Do not pause merely to ask whether to continue."
AUTHORITY_BOUNDARY = (
    "Persistence never supplies authority to commit, push, open or update a "
    "PR, merge, deploy, or take a destructive action."
)
REAL_BLOCKER_EXCEPTION = (
    "Stop when a real blocker prevents progress or before an action that "
    "needs new authority."
)
LITERAL_QUESTION_RULE = (
    "Answer the user's literal question before related context or adjacent work."
)


def normalized_text(path):
    with open(path, encoding="utf-8") as handle:
        return re.sub(r"\s+", " ", handle.read())


class TestNamedConstraintsAcrossHarnesses(unittest.TestCase):
    def test_persistence_through_done_preserves_authority_boundaries(self):
        for harness, path in SURFACES.items():
            with self.subTest(harness=harness):
                text = normalized_text(path)
                self.assertIn(PERSISTENCE_RULE, text)
                self.assertIn(NO_PERMISSION_PAUSE, text)
                self.assertIn(REAL_BLOCKER_EXCEPTION, text)
                self.assertIn(AUTHORITY_BOUNDARY, text)

    def test_literal_question_is_answered_first(self):
        for harness, path in SURFACES.items():
            with self.subTest(harness=harness):
                self.assertIn(LITERAL_QUESTION_RULE, normalized_text(path))

    def test_cursor_rule_remains_always_on(self):
        cursor_text = normalized_text(SURFACES["Cursor"])
        self.assertIn("alwaysApply: true", cursor_text)


if __name__ == "__main__":
    unittest.main()
