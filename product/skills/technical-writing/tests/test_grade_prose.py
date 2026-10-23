#!/usr/bin/env python3
"""The technical-writing eval: the skill's bad example fails and the good one passes.

Run: python3 -m unittest discover -s product/skills/technical-writing/tests -v
"""
import os
import sys
import unittest

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(SKILL_DIR, "scripts"))

import grade_prose  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _read(name: str) -> str:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return handle.read()


class GradeProse(unittest.TestCase):
    def test_before_fails(self):
        hits = grade_prose.sentence_findings(_read("before.md"))
        self.assertIn("passive setup: name who acts", hits)
        self.assertIn("filler: delete the note", hits)
        self.assertIn("passive instruction: write the command", hits)
        self.assertIn("metaphor noun: name the mechanism", hits)

    def test_after_passes(self):
        self.assertEqual(grade_prose.grade(_read("after.md"), "reference"), [])

    def test_semicolon_fails(self):
        hits = grade_prose.sentence_findings("The loader parses the file; the compiler checks it.")
        self.assertEqual(hits, ["semicolon: use a period"])

    def test_chat_question_stays_silent(self):
        self.assertFalse(grade_prose.applies_to("eli5 why is the deploy failing?"))

    def test_readme_rewrite_applies(self):
        self.assertTrue(
            grade_prose.applies_to(
                "Rewrite this README section so a tired engineer gets it on the first read."
            )
        )

    def test_reference_with_steps_fails(self):
        text = "budget.mjs reads budget.json.\nFirst, click Save.\nYou will learn why the budget exists."
        hits = grade_prose.mode_findings(text, "reference")
        self.assertIn("mode: a lesson line is inside a non-tutorial", hits)
        self.assertIn("mode: steps are inside a reference", hits)

    def test_howto_without_a_step_fails(self):
        hits = grade_prose.mode_findings("The budget lives in budget.json.", "how-to")
        self.assertEqual(hits, ["mode: a lesson or task has no step"])

    def test_skill_after_example_passes_the_grader(self):
        with open(os.path.join(SKILL_DIR, "SKILL.md"), encoding="utf-8") as handle:
            skill = handle.read()
        after = _read("after.md").strip()
        self.assertIn(after, skill)
        self.assertEqual(grade_prose.grade(after, "reference"), [])

    def test_design_doc_section_names_each_rule_and_passes_the_grader(self):
        with open(os.path.join(SKILL_DIR, "SKILL.md"), encoding="utf-8") as handle:
            skill = handle.read()
        start = skill.index("## Design docs (explanation mode)")
        end = skill.index("## Write sentences to the reader")
        section = skill[start:end]
        for required in (
            'Write the team\'s decisions as "we"',
            "component as the subject",
            'Never address the reader as "you" in a design doc',
            "adopt its voice, not only its content",
            "footnote that links to a proof page",
            "the code is the source of truth and the doc follows",
            "carries that command",
            "known-answer fixture pushed through the real path",
            "exactly what the screen's heading says",
            "never jargon to replace with a paraphrase",
            "Source: no known prior art.",
        ):
            self.assertIn(required, section)
        self.assertEqual(grade_prose.sentence_findings(section), [])

    def test_you_rule_is_scoped_to_tutorial_and_howto(self):
        with open(os.path.join(SKILL_DIR, "SKILL.md"), encoding="utf-8") as handle:
            skill = handle.read()
        self.assertIn('Talk to the reader as "you", in the present tense, in a tutorial or a how-to.', skill)


if __name__ == "__main__":
    unittest.main()
