"""Pin the User-did-it lens: a step the user did by hand is the spec.

Reflect already failed a session for heavy user involvement, but no lens
looked at the steps the user performed themselves (a command run in their
own terminal, a pasted fix). These tests only pin that the lens, its FAIL
trigger, its skip rule for steps that need the person, and its hand-off to
automate-me are present, so an edit cannot drop them silently.
"""
from __future__ import annotations

from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[2]
SKILL_MD = SKILL_DIR / "SKILL.md"
LENSES_MD = SKILL_DIR / "references" / "lenses.md"
AUTOMATE_ME_MD = SKILL_DIR.parent / "automate-me" / "SKILL.md"


def _lens_row(text: str) -> str:
    rows = [line for line in text.splitlines() if line.startswith("| User-did-it |")]
    assert len(rows) == 1, rows
    return rows[0]


def test_lens_row_treats_user_steps_as_the_spec() -> None:
    row = _lens_row(LENSES_MD.read_text(encoding="utf-8"))
    assert "is the spec for what the agent should have done" in row
    assert "FAIL" in row
    assert "`automate-me`" in row


def test_lens_row_skips_steps_that_need_the_person() -> None:
    row = _lens_row(LENSES_MD.read_text(encoding="utf-8"))
    for step in ("passwords", "hardware", "approval dialogs"):
        assert step in row, step


def test_lens_row_is_grounded() -> None:
    row = _lens_row(LENSES_MD.read_text(encoding="utf-8"))
    assert "Programming by Demonstration" in row
    assert "1993" in row
    assert "http://acypher.com/wwid/" in row


def test_reflect_invokes_on_user_did_it() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    invoke = text[text.index("## When to invoke"):text.index("## Process")]
    assert "User-did-it lens" in invoke
    assert "Treat it as FAIL" in invoke


def test_automate_me_turns_user_steps_into_defaults() -> None:
    text = AUTOMATE_ME_MD.read_text(encoding="utf-8")
    assert "User-did-it" in text
    assert "standing default" in text
