import json
import os
import re
import sys
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
HOOKS_DIR = os.path.dirname(TESTS_DIR)
LLM_JUDGE_DIR = os.path.join(os.path.dirname(HOOKS_DIR), "llm-judge")
sys.path.insert(0, TESTS_DIR)
sys.path.insert(0, LLM_JUDGE_DIR)

from test_hooks import run_claude_check, run_prompt_reminder  # noqa: E402
from testing import JudgeTestCase  # noqa: E402

WORD_COUNT_RE = re.compile(r"\b(\d+) words\b")

UNCOUNTED_ARTIFACTS = {
    "fenced code blocks": "```\n" + " ".join(["code"] * 60) + "\n```",
    "markdown table rows": "\n".join(f"| row{i} | cell one | cell two |" for i in range(20)),
}


def reminder_text():
    return json.loads(run_prompt_reminder({}))["hookSpecificOutput"]["additionalContext"]


def stated_limit():
    return int(WORD_COUNT_RE.search(reminder_text()).group(1))


def prose(n):
    return " ".join(["word"] * n)


class TestReminderAndCheckerAgree(JudgeTestCase):
    def test_reminder_states_exactly_one_word_limit(self):
        self.assertEqual(len(WORD_COUNT_RE.findall(reminder_text())), 1, reminder_text())

    def test_checker_allows_exactly_the_stated_limit(self):
        blocked, err = run_claude_check({"last_assistant_message": prose(stated_limit())})
        self.assertFalse(blocked, err)

    def test_checker_blocks_one_word_past_the_stated_limit(self):
        blocked, _ = run_claude_check({"last_assistant_message": prose(stated_limit() + 1)})
        self.assertTrue(blocked)

    def test_reminder_names_every_artifact_the_checker_does_not_count(self):
        reminder = reminder_text()
        for label, artifact in UNCOUNTED_ARTIFACTS.items():
            with self.subTest(label=label):
                self.assertIn(label, reminder)
                message = f"{prose(stated_limit())}\n\n{artifact}"
                blocked, err = run_claude_check({"last_assistant_message": message})
                self.assertFalse(blocked, err)


if __name__ == "__main__":
    unittest.main()
