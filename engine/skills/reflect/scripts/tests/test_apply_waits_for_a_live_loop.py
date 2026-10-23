#!/usr/bin/env python3
"""reflect step 5 presents inside a live loop and applies once it closes, and repeats an ETA only when it changes."""
from __future__ import annotations

import os
import re
import unittest

SKILL = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "SKILL.md")


def step_five() -> str:
    with open(SKILL, encoding="utf-8") as handle:
        text = re.sub(r"\s+", " ", handle.read())
    start = text.index("### 5. Auto-worktree apply")
    return text[start:text.index("### 5b.", start)]


class TestApplyWaitsForALiveLoop(unittest.TestCase):
    def test_a_live_loop_is_named_by_its_three_signs(self):
        section = step_five()
        self.assertIn("save now and apply later", section)
        self.assertIn("chat still gets one sentence", section)
        for sign in ("a comment watch is armed", "review threads are open", "above 200k tokens"):
            self.assertIn(sign, section)

    def test_the_apply_waits_for_the_loop_or_runs_in_a_separate_session(self):
        section = step_five()
        self.assertIn("waits until the loop closes, or runs in a separate session", section)
        self.assertIn("or once a live loop has closed, fire a", section)
        self.assertIn("A live loop defers the apply; it does not skip it.", section)

    def test_an_eta_is_repeated_only_when_it_changes(self):
        section = step_five()
        self.assertIn("repeated only when it changes, with the reason", section)
        self.assertIn("My Philosophy on Alerting", section)


if __name__ == "__main__":
    unittest.main()
