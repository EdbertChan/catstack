#!/usr/bin/env python3
"""Pin the rule-text requirements this skill states, and the gates that run them.

A mined rule reaches skill prose through this skill, so the two requirements on
that text -- dateless, and stated as the general lesson -- live in its own
bullet. Each one names the checker that enforces it; a requirement whose
checker is renamed or deleted has to fail here rather than survive as prose
nothing runs.
"""
from __future__ import annotations

import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.join(os.path.dirname(HERE), "SKILL.md")
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
DATE_GATE = "scripts/ci/check_no_dated_provenance.py"
SCOPE_GATE = "engine/skills/make-pr/scripts/rule_scope_check.py"


def skill_text() -> str:
    with open(SKILL, encoding="utf-8") as handle:
        return handle.read()


def rule_bullet() -> str:
    for line in skill_text().splitlines():
        if line.startswith("- **No dates or incident narrative"):
            return line
    return ""


class TestRuleTextRequirements(unittest.TestCase):
    def test_the_rule_bullet_bans_dates_and_incident_narrative(self):
        self.assertIn("dateless", rule_bullet())
        self.assertIn(DATE_GATE, rule_bullet())

    def test_the_rule_bullet_requires_the_general_lesson_in_the_main_sentence(self):
        bullet = rule_bullet()
        self.assertIn("general lesson", bullet)
        self.assertIn("only as an example", bullet)

    def test_the_rule_bullet_names_the_checker_that_reads_the_rule_scope(self):
        self.assertIn(SCOPE_GATE, rule_bullet())

    def test_both_named_checkers_exist(self):
        for gate in (DATE_GATE, SCOPE_GATE):
            self.assertTrue(os.path.isfile(os.path.join(REPO_ROOT, gate)), gate)

    def test_a_judge_that_cannot_answer_is_not_a_pass(self):
        self.assertIn("could not answer", rule_bullet())


if __name__ == "__main__":
    unittest.main()
