"""Contract tests for reflect's mining and lifecycle references."""

import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]


class ReferenceDocsTest(unittest.TestCase):
    def test_lifecycle_reference_is_linked_and_names_its_contract(self):
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        lifecycle = (SKILL_ROOT / "references" / "lifecycle.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("(references/lifecycle.md)", skill)
        for required in (
            "## Signals it reads",
            "## The proposal rules",
            "`clean`",
            "`changed`",
            "`blocked`",
            "## Never merge",
        ):
            with self.subTest(required=required):
                self.assertIn(required, lifecycle)

    def test_session_mine_reference_names_ranking_and_order_tools(self):
        session_mine = (SKILL_ROOT / "references" / "session-mine.md").read_text(
            encoding="utf-8"
        )

        for required in (
            "--half-life-days",
            "engine/runbook/pinned.txt",
            "step_order.py",
            "compile.py backtest",
            "replay_gate.py",
        ):
            with self.subTest(required=required):
                self.assertIn(required, session_mine)


if __name__ == "__main__":
    unittest.main()
