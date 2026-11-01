"""The reflect apply step starts hook and skill fixes in their own XIRP session."""

import os
import unittest

SKILL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "SKILL.md")


def apply_step_text() -> str:
    with open(SKILL, encoding="utf-8") as handle:
        text = handle.read()
    start = text.index("### 5. Auto-worktree apply")
    return text[start : text.index("### 6.", start)]


class TestReflectXirpFork(unittest.TestCase):
    def test_apply_step_forks_an_xirp_session_with_a_brief(self) -> None:
        step = apply_step_text()
        self.assertIn("xirp session new --goal", step)
        self.assertIn("self-contained brief", step)

    def test_apply_step_keeps_the_subagent_fallback_without_xirp(self) -> None:
        self.assertIn("Without `xirp`", apply_step_text())

    def test_apply_step_names_the_nudging_hook_and_still_never_merges(self) -> None:
        step = apply_step_text()
        self.assertIn("engine/hooks/fork-hook-skill-work/", step)
        self.assertIn("never-merge", step)


if __name__ == "__main__":
    unittest.main()
