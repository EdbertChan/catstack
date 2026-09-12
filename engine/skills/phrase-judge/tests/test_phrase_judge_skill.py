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
        self.assertIn(
            "writing or fixing any catstack checker that decides based on what a",
            frontmatter,
        )

    def test_points_to_phrase_dictionary_path(self):
        with open(SKILL_PATH, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("phrases/<checker>.json", text)


if __name__ == "__main__":
    unittest.main()
