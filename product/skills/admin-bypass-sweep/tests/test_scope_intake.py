from __future__ import annotations

import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SKILL = HERE.parent / "SKILL.md"
ANSWERED = HERE / "scope_answered_reply.md"
UNANSWERED = HERE / "scope_unanswered_consent_only_reply.md"


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


class TestScopeIntake(unittest.TestCase):
    def test_step_2_separates_scope_from_consent(self):
        skill = SKILL.read_text(encoding="utf-8")

        self.assertIn("Ask the scope question in this turn, and ask only that question.", skill)
        self.assertIn("Do not request the\nliteral consent sentence in the same message", skill)
        self.assertIn("After scope is answered", skill)
        self.assertIn("in a separate turn", skill)

    def test_consent_only_reply_resolves_to_narrowest_scope(self):
        skill = SKILL.read_text(encoding="utf-8")
        fixture = normalized(UNANSWERED)

        self.assertIn("If the human's reply carries only the literal consent sentence", skill)
        self.assertIn("not as a scope answer", skill)
        self.assertIn("narrowest offered scope", fixture)
        self.assertIn("single-PR groups only", fixture)
        self.assertIn("remain out of scope", fixture)

    def test_scope_answered_fixture_resolves_to_stated_scope(self):
        fixture = normalized(ANSWERED)

        self.assertIn('User replies: "Run the full grouped plan."', fixture)
        self.assertIn("scope is answered before consent is requested", fixture)
        self.assertIn("resolved scope is the full grouped plan", fixture)
        self.assertIn("explicitly chose the larger offered scope", fixture)


if __name__ == "__main__":
    unittest.main()
