#!/usr/bin/env python3
"""reflect interactive mode writes its findings into the PR, and chat gets
one sentence.

The Accepted / Backlog / Route-to-automate-me / Rejected list, the cost
audit, the feedback-loop line and any open question belong in the PR body
(or a findings file on the PR branch), where the user reads, answers and
vetoes. The chat output of a pass is exactly one sentence: a PR was opened,
with its link, plus "one question in the PR" when a finding needs a human
decision. Headless mode (5b) keeps GitHub review as its gate. These
assertions pin the wording because the SKILL.md is edited often and a
"present the list" sentence is easy to slip back in.
"""
from __future__ import annotations

import os
import re
import unittest

SKILL = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "SKILL.md",
)


def skill_text() -> str:
    with open(SKILL, encoding="utf-8") as handle:
        return re.sub(r"\s+", " ", handle.read())


def section(text: str, start: str, end: str) -> str:
    begin = text.index(start)
    return text[begin:text.index(end, begin)]


class TestFindingsGoToThePr(unittest.TestCase):
    def test_step_seven_writes_the_findings_into_the_pr(self):
        text = skill_text()
        self.assertIn("### 7. Write the findings into the PR", text)
        self.assertNotIn("### 7. Summarize", text)
        step7 = text[text.index("### 7."):]
        self.assertIn("goes into the PR body", step7)
        self.assertIn("never into chat", step7)

    def test_step_seven_keeps_the_list_as_the_pr_body_format(self):
        step7 = skill_text()[skill_text().index("### 7."):]
        for line in ("Edits applied:", "Backlogged:", "Dropped:", "Cost audit:", "Feedback-loop check:", "Open question:"):
            self.assertIn(line, step7, line)

    def test_chat_output_is_exactly_one_sentence_with_the_pr_link(self):
        step7 = skill_text()[skill_text().index("### 7."):]
        self.assertIn("exactly one sentence", step7)
        self.assertIn("with its link", step7)
        self.assertIn("one question in the PR", step7)
        self.assertIn("Nothing else from this list goes into chat", step7)

    def test_step_five_does_not_present_the_list_in_chat(self):
        step5 = section(skill_text(), "### 5. ", "### 5b.")
        self.assertNotIn("Present the full", step5)
        self.assertIn("not into chat", step5)
        self.assertIn("Wait for the PR URL", step5)
        self.assertIn("exactly one sentence", step5)

    def test_veto_still_works_by_chat_against_the_open_pr(self):
        step5 = section(skill_text(), "### 5. ", "### 5b.")
        self.assertIn("drop item 2", step5)
        self.assertIn("abort reflect apply", step5)
        self.assertIn("against the open PR", step5)

    def test_intro_no_longer_says_the_parent_presents_findings(self):
        text = skill_text()
        self.assertNotIn("The parent presents findings", text)
        self.assertNotIn("presenting the Accepted / Backlog", text)

    def test_headless_mode_is_unchanged(self):
        step5b = section(skill_text(), "### 5b.", "### 6.")
        self.assertIn("GitHub review is the gate", step5b)
        self.assertIn("**Never merge.**", step5b)
        self.assertIn("mark-dispatched", step5b)


if __name__ == "__main__":
    unittest.main()
