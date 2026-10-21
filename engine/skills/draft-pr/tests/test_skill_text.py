#!/usr/bin/env python3
"""draft-pr skill prose: preflight before body, one publish path.

Run: python3 -m unittest discover -s engine/skills/draft-pr/tests -v
"""
from __future__ import annotations

import os
import unittest

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _skill_text() -> str:
    with open(os.path.join(SKILL_DIR, "SKILL.md"), encoding="utf-8") as handle:
        return handle.read()


class DraftPrEvidence(unittest.TestCase):
    """The PR body carries its numbers and its worked examples the same way every time."""

    def setUp(self):
        self.text = _skill_text()

    def test_summary_owns_the_delta_and_links_its_live_source(self):
        self.assertIn("the Summary carries that number\nbefore and after", self.text)
        self.assertIn("a link to the live query or dashboard it was read\nfrom and to the tracking ticket", self.text)
        self.assertIn("The ticket states the problem and its\nsize and never the fix", self.text)


class DraftPrOrder(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(SKILL_DIR, "SKILL.md"), encoding="utf-8") as handle:
            self.text = handle.read()

    def test_runs_make_pr_preflight_before_drafting_body(self):
        self.assertIn("Run its preflight classification before drafting any PR body", self.text)
        self.assertIn("commit-scoped", self.text)

    def test_choose_mergify_vs_gh_once_before_first_push(self):
        self.assertIn("Choose Mergify vs `gh` once", self.text)
        self.assertIn("before the first push", self.text)


if __name__ == "__main__":
    unittest.main()
