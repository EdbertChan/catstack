#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path

SKILL = (Path(__file__).resolve().parents[1] / "SKILL.md").read_text(encoding="utf-8")


class TestReviewThreadDecisionTree(unittest.TestCase):
    def test_do_not_defaults_to_decision_tree(self):
        self.assertIn(
            "Do not resolve review threads to unblock a merge by default. Decision tree:",
            SKILL,
        )

    def test_babysit_bot_thread_resolves_after_head_addresses(self):
        start = SKILL.index(
            "**Automated review thread under an explicit babysit-until-merged job**"
        )
        end = SKILL.index("**Deferral required for human reviewer threads:**")
        bot = SKILL[start:end]
        self.assertIn("current head addresses the thread", bot)
        self.assertIn("or the thread is outdated", bot)
        self.assertIn("Do not bounce that to the user", bot)

    def test_human_thread_needs_recorded_deferral(self):
        start = SKILL.index("**Deferral required for human reviewer threads:**")
        end = SKILL.index("**Otherwise leave the thread open:**")
        human = SKILL[start:end]
        self.assertIn("record the deferral on the PR", human)
        self.assertIn("This rule alone never", human)
        self.assertIn("authorizes resolving a human thread", human)

    def test_no_babysit_leaves_thread_open(self):
        start = SKILL.index("**Otherwise leave the thread open:**")
        otherwise = SKILL[start : start + 200]
        self.assertIn("no babysit-until-merged", otherwise)
        self.assertIn("leave it open", otherwise)


if __name__ == "__main__":
    unittest.main()
