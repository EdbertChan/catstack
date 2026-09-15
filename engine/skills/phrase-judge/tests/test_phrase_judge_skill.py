import os
import unittest


SKILL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "SKILL.md"
)


class TestPhraseJudgeSkill(unittest.TestCase):
    def test_skill_file_exists(self):
        self.assertTrue(os.path.isfile(SKILL_PATH))

    def test_frontmatter_has_name_and_description(self):
        with open(SKILL_PATH, encoding="utf-8") as handle:
            text = handle.read()
        self.assertTrue(text.startswith("---\n"))
        frontmatter = text.split("---", 2)[1]
        self.assertIn("name: phrase-judge", frontmatter)
        self.assertIn("description:", frontmatter)
        self.assertIn("any checker, gate, or lint, in any", frontmatter)
        self.assertNotIn("any catstack checker", frontmatter)

    def test_word_lists_are_replaced_not_trimmed(self):
        with open(SKILL_PATH, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("never trim, extend,", text)
        self.assertIn("the check reports unchecked and warns; it never passes silently", text)

    def test_points_to_phrase_dictionary_path(self):
        with open(SKILL_PATH, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("phrases/<checker>.json", text)


if __name__ == "__main__":
    unittest.main()
