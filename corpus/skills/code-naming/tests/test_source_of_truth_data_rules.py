"""Pin the no-silent-limit and one-computation rules in the code-naming source-of-truth section."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "SKILL.md"


def _source_of_truth_section(text: str) -> str:
    match = re.search(r"^## Source of truth, never string parsing\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    return match.group(1) if match else ""


class SourceOfTruthDataRulesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.section = _source_of_truth_section(SKILL.read_text(encoding="utf-8"))

    def test_section_is_found(self) -> None:
        self.assertTrue(self.section)

    def test_data_limit_must_be_configured_with_its_reason(self) -> None:
        self.assertIn("No silent cap on data", self.section)
        self.assertIn("configured\n  value with its reason beside it", self.section)
        self.assertIn('"every run" or "all', self.section)

    def test_two_views_share_one_loader_and_computation(self) -> None:
        self.assertIn("share one loader and one computation", self.section)
        self.assertIn("treat the mismatch as a bug", self.section)

    def test_each_rule_carries_its_grounding(self) -> None:
        self.assertIn("12factor.net/config", SKILL.read_text(encoding="utf-8"))
        self.assertIn("pragprog.com/titles/tpp20", self.section)

    def test_missing_section_reads_as_empty(self) -> None:
        self.assertEqual(_source_of_truth_section("## Other\nbody\n"), "")


if __name__ == "__main__":
    unittest.main()
