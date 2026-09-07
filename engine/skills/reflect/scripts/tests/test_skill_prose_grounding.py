"""Pin the synthesis-step grounding gate in reflect's own prose.

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
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[2]
SKILL_MD = SKILL_DIR / "SKILL.md"
LENSES_MD = SKILL_DIR / "references" / "lenses.md"


def _synthesize_section(text: str) -> str:
    start = text.index("### 4. Synthesize")
    end = text.index("### 5.", start)
    return text[start:end]


def test_synthesize_step_requires_grounding_or_no_prior_art() -> None:
    section = _synthesize_section(SKILL_MD.read_text(encoding="utf-8"))
    assert "Grounding gate" in section
    assert re.search(r"no known prior art", section)
    assert "Backlog for grounding" in section
    for field in ("author", "title", "year", "URL"):
        assert field in section, field


def test_lens_output_carries_the_principle_or_no_prior_art() -> None:
    text = LENSES_MD.read_text(encoding="utf-8")
    assert "established principle it instantiates" in text
    assert "no known prior art" in text
    assert "grounding gate" in text
