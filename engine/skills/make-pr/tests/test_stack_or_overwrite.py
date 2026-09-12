import os
import unittest

SKILL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "SKILL.md")
HEADING = "## Stack on top, or overwrite the branch"


class TestStackOrOverwrite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(SKILL, encoding="utf-8") as handle:
            cls.text = handle.read()
        cls.section = cls.text.split(HEADING, 1)[-1].split("\n## ", 1)[0]

    def test_the_skill_has_the_section(self):
        self.assertIn(HEADING, self.text)

    def test_the_section_names_both_treatments(self):
        self.assertIn("**Stack on top**", self.section)
        self.assertIn("**Overwrite the branch**", self.section)

    def test_stacking_is_for_a_claim_that_still_holds(self):
        self.assertIn("the claim still holds", self.section)

    def test_overwriting_is_for_a_diff_that_stopped_matching_the_claim(self):
        for trigger in ("work already on the base", "mixes review units", "ships a second claim"):
            with self.subTest(trigger=trigger):
                self.assertIn(trigger, self.section)

    def test_overwriting_requires_a_lease_and_a_backup_branch(self):
        self.assertIn("--force-with-lease", self.section)
        self.assertIn("backup/pr<number>-<short-sha>", self.section)

    def test_a_lease_failure_stops_the_overwrite(self):
        self.assertIn("re-read it and decide again", self.section)

    def test_the_choice_is_not_a_question_for_the_user(self):
        self.assertIn("never by\nasking the user", self.section)


if __name__ == "__main__":
    unittest.main()
