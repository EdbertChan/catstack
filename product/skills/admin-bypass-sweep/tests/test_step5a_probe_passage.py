#!/usr/bin/env python3
from __future__ import annotations

import re
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SKILL = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
FIXTURE = (SKILL_DIR / "tests" / "fires_step5a_names_probe.md").read_text(encoding="utf-8")


def step5a_passage() -> str:
    match = re.search(r"## Step 5a:.*?(?=\n## Step 6:)", SKILL, re.S)
    if not match:
        raise AssertionError("Step 5a passage not found")
    return match.group(0)


class TestStep5aProbePassage(unittest.TestCase):
    def test_fixture_names_the_assertions(self):
        self.assertIn("scripts/probe_branch_rebase.sh", FIXTURE)
        for outcome in ("OK", "FAIL", "UNCHECKED"):
            self.assertIn(outcome, FIXTURE)
        self.assertIn("rm -rf", FIXTURE)

    def test_step5a_names_probe_and_all_three_outcomes(self):
        passage = step5a_passage()
        self.assertIn("scripts/probe_branch_rebase.sh", passage)
        for outcome in ("OK", "FAIL", "UNCHECKED"):
            self.assertRegex(passage, rf"`{outcome}`")

    def test_step5a_no_longer_contains_improvised_removal(self):
        self.assertNotIn("rm -rf", step5a_passage())


if __name__ == "__main__":
    unittest.main()
