#!/usr/bin/env python3
"""Part 3 (replies to a comment on a document) ships in SKILL.md with its fixtures.

Run: python3 -m unittest discover -s product/skills/diu/tests -v
"""
import os
import unittest

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.join(SKILL_DIR, "tests")
COMMENT_WORD_LIMIT = 40


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class CommentReplyRule(unittest.TestCase):
    def setUp(self):
        self.text = read(os.path.join(SKILL_DIR, "SKILL.md"))

    def test_rule_has_its_own_section(self):
        self.assertIn("## Part 3: replies to a comment on a document", self.text)

    def test_rule_states_the_cap_once_in_the_section_and_once_in_the_description(self):
        self.assertEqual(self.text.count(f"ELI5, under {COMMENT_WORD_LIMIT} words"), 2, self.text)

    def test_rule_names_what_the_count_leaves_out(self):
        self.assertIn("outside fenced code blocks and\n   URLs", self.text)

    def test_rule_names_the_hook_that_enforces_it(self):
        self.assertIn("`engine/hooks/diu-stop` enforces this before the reply is posted", self.text)

    def test_rule_refuses_an_unreadable_body_instead_of_passing_it(self):
        self.assertIn("refused as unchecked, never passed as clean", self.text)

    def test_fires_fixture_is_a_comment_thread_reply(self):
        fixture = read(os.path.join(TESTS_DIR, "comment_reply_fires_example.md"))
        self.assertIn("comment thread", fixture)
        self.assertIn("under 40 words", fixture)

    def test_stays_silent_fixture_is_a_chat_reply(self):
        fixture = read(os.path.join(TESTS_DIR, "comment_reply_stays_silent_example.md"))
        self.assertIn("not a comment thread", fixture)
        self.assertIn("does not apply", fixture)


if __name__ == "__main__":
    unittest.main()
