"""Pin the User-did-it lens: a step the user did by hand is the spec.

Reflect already failed a session for heavy user involvement, but no lens
looked at the steps the user performed themselves (a command run in their
own terminal, a pasted fix). These tests only pin that the lens, its FAIL
trigger, its skip rule for steps that need the person, and its hand-off to
automate-me are present, so an edit cannot drop them silently.
"""
from __future__ import annotations

import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[2]
SKILL_MD = SKILL_DIR / "SKILL.md"
LENSES_MD = SKILL_DIR / "references" / "lenses.md"
AUTOMATE_ME_MD = SKILL_DIR.parent / "automate-me" / "SKILL.md"


class TestUserDidItLens(unittest.TestCase):
    def _lens_row(self) -> str:
        text = LENSES_MD.read_text(encoding="utf-8")
        rows = [line for line in text.splitlines() if line.startswith("| User-did-it |")]
        self.assertEqual(len(rows), 1, rows)
        return rows[0]

    def test_lens_row_treats_user_steps_as_the_spec(self) -> None:
        row = self._lens_row()
        self.assertIn("is the spec for what the agent should have done", row)
        self.assertIn("FAIL", row)
        self.assertIn("`automate-me`", row)

    def test_lens_row_skips_steps_that_need_the_person(self) -> None:
        row = self._lens_row()
        for step in ("passwords", "hardware", "approval dialogs"):
            with self.subTest(step=step):
                self.assertIn(step, row)

    def test_lens_row_is_grounded(self) -> None:
        row = self._lens_row()
        self.assertIn("Programming by Demonstration", row)
        self.assertIn("1993", row)
        self.assertIn("http://acypher.com/wwid/", row)

    def test_reflect_invokes_on_user_did_it(self) -> None:
        text = SKILL_MD.read_text(encoding="utf-8")
        invoke = text[text.index("## When to invoke"):text.index("## Process")]
        self.assertIn("User-did-it lens", invoke)
        self.assertIn("Treat it as FAIL", invoke)

    def test_automate_me_turns_user_steps_into_defaults(self) -> None:
        text = AUTOMATE_ME_MD.read_text(encoding="utf-8")
        self.assertIn("User-did-it", text)
        self.assertIn("standing default", text)

    def test_reflect_names_the_live_hook(self) -> None:
        text = SKILL_MD.read_text(encoding="utf-8")
        invoke = text[text.index("## When to invoke"):text.index("## Process")]
        self.assertIn("The `user-did-it` hook flags these live", invoke)


if __name__ == "__main__":
    unittest.main()
