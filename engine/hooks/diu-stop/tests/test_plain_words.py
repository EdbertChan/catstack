import os
import sys
import unittest

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LLM_JUDGE_DIR = os.path.join(os.path.dirname(HOOK_DIR), "llm-judge")
sys.path.insert(0, LLM_JUDGE_DIR)

import phrases

PHRASES_DIR = os.path.join(HOOK_DIR, "phrases")
PREFIX = "plain-words-"
CATEGORIES = (
    "plain-words-made-up-labels",
    "plain-words-code-names",
    "plain-words-internal-names",
    "plain-words-tech-jargon",
    "plain-words-status-words",
)
EDGE = ".,;:()!?\"'"


def _is_pr_number(token):
    return token.startswith("#") and token.strip(EDGE).lstrip("#").isdigit()


def _is_date(token):
    parts = token.strip(EDGE).split("-")
    return len(parts) == 3 and len(parts[0]) == 4 and all(part.isdigit() for part in parts)


def _load(checker):
    return phrases.load(checker, directory=PHRASES_DIR)


class TestPlainWords(unittest.TestCase):
    def test_every_category_file_is_listed(self):
        found = sorted(name[:-5] for name in os.listdir(PHRASES_DIR) if name.startswith(PREFIX) and name.endswith(".json"))
        self.assertEqual(found, sorted(CATEGORIES))

    def test_each_category_loads_and_reads_the_exchange(self):
        for checker in CATEGORIES:
            with self.subTest(checker=checker):
                dictionary = _load(checker)
                self.assertEqual(dictionary["reads"], "exchange")
                self.assertGreaterEqual(len(dictionary["match"]), 3)
                self.assertGreaterEqual(len(dictionary["not_match"]), 2)
                self.assertTrue(dictionary["on_hit"].startswith("plain-words:"))

    def test_no_phrase_names_a_pr_number_or_a_date(self):
        for checker in CATEGORIES:
            dictionary = _load(checker)
            for phrase in [dictionary["meaning"], *dictionary["match"], *dictionary["not_match"]]:
                for token in phrase.split():
                    with self.subTest(checker=checker, token=token):
                        self.assertFalse(_is_pr_number(token))
                        self.assertFalse(_is_date(token))

    def test_no_phrase_sits_in_two_categories(self):
        seen = {}
        for checker in CATEGORIES:
            dictionary = _load(checker)
            for phrase in dictionary["match"] + dictionary["not_match"]:
                self.assertNotIn(phrase, seen, f"{phrase!r} is in {seen.get(phrase)} and {checker}")
                seen[phrase] = checker

    def test_a_pr_number_and_a_date_are_recognised(self):
        self.assertTrue(_is_pr_number("#412."))
        self.assertTrue(_is_date("2026-09-11"))
        self.assertFalse(_is_pr_number("#tag"))
        self.assertFalse(_is_date("engine-runtime"))


if __name__ == "__main__":
    unittest.main()
