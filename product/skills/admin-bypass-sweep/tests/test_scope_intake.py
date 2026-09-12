from pathlib import Path
import unittest


SKILL_DIR = Path(__file__).resolve().parents[1]
SKILL_MD = SKILL_DIR / "SKILL.md"
TESTS_DIR = SKILL_DIR / "tests"


def read(name: str) -> str:
    return (TESTS_DIR / name).read_text(encoding="utf-8")


def prose(text: str) -> str:
    return " ".join(text.split())


def step_2() -> str:
    text = SKILL_MD.read_text(encoding="utf-8")
    return text.split("## Step 2: Confirm scope", 1)[1].split("## Step 3:", 1)[0]


class ScopeIntakeTest(unittest.TestCase):
    def test_step_2_separates_scope_question_from_consent_sentence_request(self):
        text = prose(step_2())
        self.assertIn("Ask the scope question by itself in this turn", text)
        self.assertIn("Do not ask for the STOP section's exact", text)
        self.assertIn("in the same turn as this scope question", text)
        self.assertIn("Only after scope is resolved", text)
        self.assertIn("in a separate turn", text)

    def test_step_2_resolves_unanswered_scope_to_narrowest_offer(self):
        text = prose(step_2())
        self.assertIn("resolves scope to the narrowest option that was offered", text)
        self.assertIn("does not carry variable scope content", text)
        self.assertIn("Multi-PR stacks require an explicit second answer naming them", text)
        self.assertIn("Without that answer, leave every multi-PR stack out of scope", text)

    def test_scope_answered_fixture_resolves_to_stated_scope(self):
        text = prose(read("scope_answered_reply_resolves_stated_scope.md"))
        self.assertIn('User says: "Include single-PR groups and the #42 -> #43 -> #44 stack."', text)
        self.assertIn("explicit second answer naming the multi-PR stack", text)
        self.assertIn("resolves to the stated scope", text)
        self.assertIn("in a separate turn", text)

    def test_scope_unanswered_fixture_resolves_to_singles_only(self):
        text = prose(read("scope_unanswered_reply_resolves_narrowest.md"))
        self.assertIn('User says: "I understand this bypasses CI and force-merges to master"', text)
        self.assertIn("carries only the exact consent sentence", text)
        self.assertIn("single-PR groups only", text)
        self.assertIn("multi-PR stacks require an explicit second answer naming them", text)


if __name__ == "__main__":
    unittest.main()
