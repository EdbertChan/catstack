from __future__ import annotations

import unittest
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1] / "SKILL.md"


class TestScopeContract(unittest.TestCase):
    def test_subagent_step_names_the_scope_contract(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("spawn a **fresh read-only subagent**", text)
        self.assertIn("principle-subagent-inherits-scope", text)


if __name__ == "__main__":
    unittest.main()
