"""Pin reflect's investigation gates in its own prose.

The rule: before an Accepted finding becomes skill prose, name the
established principle it instantiates (with a source) or say "no known
prior art"; otherwise it goes to Backlog. A prior pass shipped two
principle skills whose rules restated real literature (fail fast, PEP 20,
control totals, mutation testing) in invented words, and nothing in the
reflect flow asked for the source. These tests only pin that the rule and
its lens-side duty are present, so an edit cannot drop them silently.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[2]
SKILL_MD = SKILL_DIR / "SKILL.md"
LENSES_MD = SKILL_DIR / "references" / "lenses.md"


def _synthesize_section(text: str) -> str:
    start = text.index("### 4. Synthesize")
    end = text.index("### 5.", start)
    return text[start:end]


def _step5_section(text: str) -> str:
    start = text.index("### 5. Present findings + auto-worktree apply")
    end = text.index("### 5b.", start)
    return text[start:end]


class TestSkillProseGrounding(unittest.TestCase):
    def test_synthesize_step_requires_grounding_or_no_prior_art(self) -> None:
        section = _synthesize_section(SKILL_MD.read_text(encoding="utf-8"))
        self.assertIn("Grounding gate", section)
        self.assertRegex(section, re.compile(r"no known prior art"))
        self.assertIn("Backlog for grounding", section)
        for field in ("author", "title", "year", "URL"):
            self.assertIn(field, section, field)

    def test_lens_output_carries_the_principle_or_no_prior_art(self) -> None:
        text = LENSES_MD.read_text(encoding="utf-8")
        self.assertIn("established principle it instantiates", text)
        self.assertIn("no known prior art", text)
        self.assertIn("grounding gate", text)

    def test_apply_waits_for_complete_fanout_and_synthesis(self) -> None:
        section = _step5_section(SKILL_MD.read_text(encoding="utf-8"))
        self.assertIn("apply nothing on a fan-out that did not return", section)
        self.assertIn("step 3's reviewers reported", section)
        self.assertIn("step 4's synthesis", section)
        self.assertIn("grounding gate", section)
        self.assertIn("say plainly that the pass is partial", section)
        self.assertIn("which lenses are missing", section)
        self.assertIn("Unreturned reviewers are not reviewers that passed", section)
