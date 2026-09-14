#!/usr/bin/env python3
from __future__ import annotations

import re
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SKILL = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
FIXTURE = (Path(__file__).resolve().parent / "stack_branch_landing_fixture.md").read_text(encoding="utf-8")


def step_6() -> str:
    match = re.search(r"^## Step 6:.*?(?=^## )", SKILL, re.M | re.S)
    if match is None:
        raise AssertionError("Step 6 section not found")
    return match.group(0)


class TestStep6VerifierTally(unittest.TestCase):
    def setUp(self) -> None:
        self.step = step_6()
        self.compact_step = " ".join(self.step.split())

    def test_step_6_names_the_trunk_ancestry_verifier(self):
        self.assertIn("engine/hooks/gh-write-verification/verify_pr_landed_on_trunk.sh", self.step)

    def test_step_6_maps_all_documented_status_codes(self):
        for code, outcome in (
            ("exit 0", "merged"),
            ("exit 1", "merged-but-not-on-trunk"),
            ("exit 3", "unchecked"),
        ):
            self.assertIn(code, self.step)
            self.assertIn(outcome, self.step)

    def test_gh_pr_view_state_alone_cannot_drive_the_merged_tally(self):
        self.assertIn("A merged tally may not be computed from `gh pr view` state alone", self.compact_step)
        self.assertNotIn("state,mergedAt", self.step)
        self.assertIn("Only exit 0 increments the merged count", self.compact_step)

    def test_exit_3_is_never_merged(self):
        self.assertIn("Exit 3 is never reported as merged", self.step)

    def test_stack_branch_fixture_is_no_longer_counted_as_merged(self):
        self.assertIn("#1789\tMERGED", FIXTURE)
        self.assertIn("Old Step 6 outcome:\n\n```text\nmerged\n```", FIXTURE)
        self.assertIn("exit 1", FIXTURE)
        self.assertIn("New Step 6 outcome:\n\n```text\nmerged-but-not-on-trunk\n```", FIXTURE)


if __name__ == "__main__":
    unittest.main()
