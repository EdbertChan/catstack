#!/usr/bin/env python3
"""reflect step 4 requires three labelled parts per finding, and step 7 to
carry them plus the catch's backtest result.

A finding whose fix has nothing watching for a repeat is how the same lesson
comes back next session, so the catch is designed alongside the fix and
backtested against the transcript that motivated it. These assertions pin the
wording because the SKILL.md is edited often and the requirement is easy to
soften into a suggestion.
"""
from __future__ import annotations

import os
import re
import unittest

SKILL = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "SKILL.md",
)


def skill_text() -> str:
    with open(SKILL, encoding="utf-8") as handle:
        return re.sub(r"\s+", " ", handle.read())


class TestThreePartFindings(unittest.TestCase):
    def test_step_four_requires_all_three_parts(self):
        text = skill_text()
        self.assertIn("Three required parts per finding.", text)
        for part in ("What happened", "Fix", "Catch"):
            self.assertIn(part, text)

    def test_a_finding_missing_a_part_is_not_ready_to_sort(self):
        self.assertIn("A finding missing one is not ready to sort.", skill_text())

    def test_the_catch_is_designed_with_the_fix_not_at_summary_time(self):
        self.assertIn("alongside the fix, not later at summary time", skill_text())

    def test_the_catch_is_backtested_against_this_transcript(self):
        text = skill_text()
        self.assertIn("Backtest it", text)
        for verdict in ("fired", "silent", "unchecked"):
            self.assertIn(verdict, text)

    def test_a_catch_that_stays_silent_on_its_own_case_does_not_count(self):
        self.assertIn(
            "A catch that stays silent on the case that motivated it is not a catch",
            skill_text(),
        )

    def test_an_unrunnable_catch_is_unchecked_never_fired(self):
        self.assertIn("could not be run is `unchecked`, never `fired`", skill_text())

    def test_no_possible_catch_must_read_as_a_gap(self):
        text = skill_text()
        self.assertIn("catch: none", text)
        self.assertIn("so the gap reads as a gap", text)

    def test_step_seven_summary_carries_the_three_parts_and_the_backtest(self):
        text = skill_text()
        self.assertIn("carries the three parts from step 4", text)
        self.assertIn("plus the catch's backtest result", text)


if __name__ == "__main__":
    unittest.main()
