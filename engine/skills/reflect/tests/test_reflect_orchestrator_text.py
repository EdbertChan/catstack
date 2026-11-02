"""The reflect orchestrator runs scripts and spawns lenses; it never reads the raw transcript."""

import os
import re
import unittest

SKILL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "SKILL.md")
PREFLIGHT_ALL = "python3 engine/skills/make-pr/scripts/preflight.py --all --base origin/main --body-file <draft>"


def skill_text() -> str:
    with open(SKILL, encoding="utf-8") as handle:
        return re.sub(r"\s+", " ", handle.read())


def orchestrator_section_text() -> str:
    text = skill_text()
    start = text.index("## Always run inside a subagent")
    return text[start : text.index("## When to invoke", start)]


def apply_step_text() -> str:
    text = skill_text()
    start = text.index("### 5. Auto-worktree apply")
    return text[start : text.index("### 6. ", start)]


class TestReflectOrchestratorText(unittest.TestCase):
    def test_orchestrator_section_names_the_scripts_it_runs(self) -> None:
        section = orchestrator_section_text()
        self.assertIn("`token_audit.py`", section)
        self.assertIn("`fanout_complete.py`", section)
        self.assertIn("`reflect_pass_state.py`", section)

    def test_orchestrator_section_says_it_spawns_and_waits(self) -> None:
        section = orchestrator_section_text()
        self.assertIn("spawns the lens agents and the synthesis agent, and waits for them", section)

    def test_orchestrator_section_says_it_does_not_read_the_transcript(self) -> None:
        section = orchestrator_section_text()
        self.assertIn("The orchestrator does not read the raw transcript itself", section)
        self.assertIn("no `Read`, `sed`, or `grep` on the session JSONL", section)
        self.assertIn("The lenses read the transcript", section)

    def test_orchestrator_section_pins_the_twenty_turn_self_report(self) -> None:
        section = orchestrator_section_text()
        self.assertIn("Its target is 20 assistant turns", section)
        self.assertIn("Past 20 turns it says so in its return", section)
        self.assertIn("orchestrator turns used: <N> against target 20", section)

    def test_orchestrator_section_names_the_cost_line_as_the_catch(self) -> None:
        section = orchestrator_section_text()
        self.assertIn("the orchestrator bucket sits below the lens bucket", section)

    def test_apply_brief_names_the_single_preflight_command(self) -> None:
        step = apply_step_text()
        self.assertIn(PREFLIGHT_ALL, step)
        self.assertIn("the one gate command", step)


if __name__ == "__main__":
    unittest.main()
