from __future__ import annotations

import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "SKILL.md"
FIRES = Path(__file__).resolve().parents[1] / "tests" / "fires_example.md"


class TestWriteAuthorityRule(unittest.TestCase):
    def test_a_writing_subagent_runs_in_its_own_worktree(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("a subagent told to write files runs in its own", text)
        self.assertIn("worktree, never the live checkout", text)

    def test_the_worktree_rule_survives_a_read_only_default(self):
        text = " ".join(SKILL.read_text(encoding="utf-8").split())
        self.assertIn(
            "even when other parts of the same prompt default to read-only",
            text,
        )

    def test_the_firing_fixture_states_the_same_worktree_rule(self):
        text = " ".join(FIRES.read_text(encoding="utf-8").split())
        self.assertIn("own worktree", text)
        self.assertNotIn("A subagent that may write gets its own worktree", text)


if __name__ == "__main__":
    unittest.main()
