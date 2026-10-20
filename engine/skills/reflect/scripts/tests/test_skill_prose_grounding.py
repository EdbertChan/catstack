"""Pin the synthesis-step grounding gate in reflect's own prose.

The rule: before an Accepted finding becomes skill prose, name the
established principle it instantiates (with a source) or say "no known
prior art"; otherwise it goes to Backlog. A prior pass shipped two
principle skills whose rules restated real literature (fail fast, PEP 20,
control totals, mutation testing) in invented words, and nothing in the
reflect flow asked for the source. These tests pin that the rule and its
lens-side duty are present, and that lesson_route.py refuses to turn a
restated existing rule into Accepted or automate-me.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[2]
SKILL_MD = SKILL_DIR / "SKILL.md"
LENSES_MD = SKILL_DIR / "references" / "lenses.md"
LESSON_ROUTE = SKILL_DIR / "scripts" / "lesson_route.py"
FIRES = SKILL_DIR / "scripts" / "tests" / "fixtures" / "restated_rule" / "fires.jsonl"


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


def test_lesson_route_gates_fires_fixture_as_already_covered() -> None:
    """Grounding is not words-in-markdown only: run the route script."""
    res = subprocess.run(
        [sys.executable, str(LESSON_ROUTE), "--from-transcript", str(FIRES), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    payload = json.loads(res.stdout)
    assert payload["bucket"] == "already-covered"
    assert payload["bucket"] != "automate-me"


def test_synthesize_step_requires_lesson_route_before_automate_me() -> None:
    section = _synthesize_section(SKILL_MD.read_text(encoding="utf-8"))
    assert "lesson_route.py" in section
    assert "already-covered" in section
    assert "does not by itself create an automate-me row" in section


def test_synthesize_step_proves_automated_reviewer_findings() -> None:
    section = _synthesize_section(SKILL_MD.read_text(encoding="utf-8"))
    assert "Proof gate for automated-reviewer findings" in section
    assert "reasoning alone" in section
    assert "real proof cases" in section
    assert "unchanged number means the instrument never tested the change" in section
    assert "re-pass after a revert is a fact, not a pass" in section
    assert "doi.org/10.1109/C-M.1978.218136" in section
