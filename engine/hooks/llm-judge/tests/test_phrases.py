import json
import os
import sys
import tempfile
import unittest

LIB_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, LIB_DIR)

import phrases


class TestPhrases(unittest.TestCase):
    def test_load_example_succeeds(self):
        dictionary = phrases.load("example")
        self.assertEqual(dictionary["checker"], "example")
        self.assertEqual(dictionary["reads"], "reply")

    def test_prompt_contains_dictionary_phrases_and_text(self):
        dictionary = phrases.load("example")
        text = "Earlier, I said the count was five. I was wrong."
        rendered = phrases.prompt(dictionary, text)
        self.assertIn(dictionary["meaning"], rendered)
        for phrase in dictionary["match"]:
            self.assertIn(phrase, rendered)
        for phrase in dictionary["not_match"]:
            self.assertIn(phrase, rendered)
        self.assertIn(text, rendered)
        self.assertIn('{"match": true|false, "closest": "<phrase or empty>"}', rendered)
        self.assertIn("quoted, negated, or described", rendered)

    def test_prompt_clips_text_to_last_4000_characters(self):
        dictionary = phrases.load("example")
        text = "a" * 1000 + "b" * 4000
        rendered = phrases.prompt(dictionary, text)
        self.assertTrue(rendered.endswith("b" * 4000))
        self.assertNotIn("a" * 1000, rendered)

    def test_job_has_hit_if_all_true_match(self):
        dictionary = phrases.load("example")
        built = phrases.job(dictionary, "/tmp/transcript.jsonl", "my mistake")
        self.assertEqual(built["hook"], "example")
        self.assertEqual(built["transcript"], "/tmp/transcript.jsonl")
        self.assertEqual(built["hit_if_all_true"], ["match"])
        self.assertEqual(built["on_hit"], dictionary["on_hit"])
        self.assertIn("my mistake", built["prompt"])

    def test_invalid_dictionaries_name_file_and_key(self):
        cases = [
            ("missing-meaning", {"checker": "missing-meaning", "reads": "reply", "match": ["x"], "not_match": [], "on_hit": "hit"}, "meaning"),
            ("empty-match", {"checker": "empty-match", "meaning": "x", "reads": "reply", "match": [], "not_match": [], "on_hit": "hit"}, "match"),
            ("bad-reads", {"checker": "bad-reads", "meaning": "x", "reads": "other", "match": ["x"], "not_match": [], "on_hit": "hit"}, "reads"),
            ("wrong-checker", {"checker": "other", "meaning": "x", "reads": "reply", "match": ["x"], "not_match": [], "on_hit": "hit"}, "checker"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            for checker, dictionary, key in cases:
                path = os.path.join(directory, f"{checker}.json")
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump(dictionary, handle)
                with self.assertRaises(ValueError) as raised:
                    phrases.load(checker, directory=directory)
                message = str(raised.exception)
                self.assertIn(path, message)
                self.assertIn(key, message)


if __name__ == "__main__":
    unittest.main()
