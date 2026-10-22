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

    def test_worked_example_section_is_in_the_schema_before_measured(self):
        self.assertIn("## Worked Example\n\nOne real case per behavior change, end to end.", self.text)
        self.assertLess(self.text.index("## Worked Example"), self.text.index("## Measured\n\nCommand:"))

    def test_worked_example_rule_requires_verbatim_output_and_named_rules(self):
        self.assertIn("Paste tool\noutput verbatim", self.text)
        self.assertIn("no `<-` notes inside the block", self.text)
        self.assertIn("Name a rule or code path by its text and file, never a\nnickname", self.text)
        self.assertIn("One truncated\nline per pattern is a catalog, not an example", self.text)

    def test_validation_lists_back_test_rows_and_live_body_fetch(self):
        self.assertIn("has a before\n  and an after row in its back test, from a run on the head", self.text)
        self.assertIn("never PUT a whole body\n  built from a stale snapshot", self.text)


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

    def test_host_dependent_rule_names_host_and_hits_in_body(self):
        self.assertIn("says which host in the PR body", self.text)
        self.assertIn("observed hits per host", self.text)

    def test_bot_pass_on_delta_is_never_approval(self):
        self.assertIn('"bot passed the delta", never as approval', self.text)


if __name__ == "__main__":
    unittest.main()
