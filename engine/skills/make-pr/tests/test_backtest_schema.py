#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
REPO_ROOT = os.path.abspath(os.path.join(SKILL_DIR, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
import check_detector_backtested as gate  # noqa: E402

FENCE_RE = re.compile(r"```md\n(## Backtest\n.*?)```", re.DOTALL)


def schema_example() -> str:
    with open(os.path.join(SKILL_DIR, "SKILL.md"), encoding="utf-8") as handle:
        match = FENCE_RE.search(handle.read())
    if match is None:
        raise AssertionError("SKILL.md has no ```md fenced ## Backtest example")
    return match.group(1)


class TestBacktestSchema(unittest.TestCase):
    def test_skill_md_example_passes_the_gate(self):
        block = gate.parse_block(schema_example())
        self.assertTrue(block.present)
        self.assertEqual(block.problems, [])

    def test_skill_md_example_names_every_field_the_gate_requires(self):
        example = schema_example().lower()
        for key in (gate.COMMAND_FIELD, *gate.COUNT_FIELDS):
            self.assertIn(f"- {key}:", example)

    def test_body_without_the_section_fails_for_a_detector_change(self):
        verdict = gate.evaluate_sources(
            "engine/hooks/x/detect.py", "LIMIT = 3\n", "LIMIT = 5\n", "## Summary\n\nRaise the limit.\n"
        )
        self.assertEqual(verdict.outcome, gate.FAIL)

    def test_body_with_the_schema_example_passes_for_a_detector_change(self):
        verdict = gate.evaluate_sources("engine/hooks/x/detect.py", "LIMIT = 3\n", "LIMIT = 5\n", schema_example())
        self.assertEqual(verdict.outcome, gate.PASS)


if __name__ == "__main__":
    unittest.main()
