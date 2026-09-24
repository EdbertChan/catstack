#!/usr/bin/env python3
"""The one-negative-per-sentence rule ships in SKILL.md with its example.

Run: python3 -m unittest discover -s product/skills/diu/tests -v
"""
import os
import sys
import unittest

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(SKILL_DIR)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))

import escape_hatch_vocab as vocab  # noqa: E402


class StackedNegativesRule(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(SKILL_DIR, "SKILL.md"), encoding="utf-8") as handle:
            self.text = handle.read()

    def test_rule_is_present(self):
        self.assertIn("One negative per sentence", self.text)

    def test_rule_demands_the_positive_action(self):
        self.assertIn("positive action", self.text)

    def test_pre_send_check_covers_stacked_negatives(self):
        self.assertIn("two or more negatives", self.text)

    def test_scenario_fixture_ships_a_stacked_example(self):
        fixture = os.path.join(SKILL_DIR, "tests", "shape_example.md")
        with open(fixture, encoding="utf-8") as handle:
            self.assertIn("no longer", handle.read())

    def test_skill_never_tells_the_author_to_write_the_retired_marker(self):
        self.assertEqual(vocab.instructs_retired_marker(self.text), [])


if __name__ == "__main__":
    unittest.main()
