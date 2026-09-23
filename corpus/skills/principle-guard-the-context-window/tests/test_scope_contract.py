from __future__ import annotations

import unittest
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1] / "SKILL.md"


class TestScopeContract(unittest.TestCase):
    def test_subagent_step_names_the_scope_contract(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("spawn a **fresh read-only subagent**", text)
        self.assertIn("principle-subagent-inherits-scope", text)

    def test_cumulative_drift_defaults_to_a_fresh_subagent_with_a_brief(self):
        text = " ".join(SKILL.read_text(encoding="utf-8").split())
        self.assertIn("Default to a fresh subagent with a written brief", text)
        for part in (
            "the goal",
            "the decisions already made",
            "the files in scope",
            "what to return",
        ):
            self.assertIn(part, text)

    def test_a_fork_is_the_exception_and_carries_its_copy_cost(self):
        text = " ".join(SKILL.read_text(encoding="utf-8").split())
        self.assertIn("A fork starts by copying the parent's entire context", text)
        self.assertIn("562K", text)
        self.assertIn("reach for one only when the child genuinely needs", text)


if __name__ == "__main__":
    unittest.main()
