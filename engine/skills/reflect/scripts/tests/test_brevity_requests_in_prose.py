"""Brevity requests and blame typed inside an ordinary message.

People ask for a shorter answer in the middle of a sentence ("eli5 < 40
words", "... /diu"), blame the agent with a question ("why didn't you just
say that"), and type slash commands inline. Each one is a signal the audit
has to count, wherever it sits in the message.
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS_DIR))
sys.path.insert(0, TESTS_DIR)

import token_audit  # noqa: E402
from test_token_audit import claude_assistant_line, claude_user_text_line, write_jsonl  # noqa: E402

USAGE = {"input_tokens": 1, "output_tokens": 1}
FIVE_ASKS = [
    "ok /diu all i want is an answer to what this setup is and where it maps to in code",
    "wait so what is the line that corresponds to the setup? eli5 < 40 words",
    "we're focusing on fix 2. Please help me understand eli5 < 40 words",
    "Jesus why the fuck didn't you just say that /diu",
    "Jesus why the fuck didn't you just say that /diu . /reflect and /automate-me",
]
NEUTRAL = "open the image-packager.sh for me"


def audit(texts):
    lines = [claude_user_text_line("paste of the earlier chat. And lets continue", ts="2026-10-22T02:33:00Z")]
    for n, text in enumerate(texts, 1):
        lines.append(claude_assistant_line(f"m{n}", f"u{n}", [{"type": "text", "text": "reply"}], USAGE))
        lines.append(claude_user_text_line(text, ts=f"2026-10-22T02:{40 + n:02d}:00Z"))
    lines.append(claude_assistant_line("mz", "uz", [{"type": "text", "text": "reply"}], USAGE))
    path = write_jsonl(lines)
    try:
        with redirect_stdout(io.StringIO()):
            result = token_audit.audit_claude(path, include_subagents=False)
    finally:
        os.unlink(path)
    return result, {f["name"]: f for f in result["flags"]}


class BrevityRequestsInProse(unittest.TestCase):
    def test_five_inline_asks_count_as_five_brevity_requests(self):
        _, flags = audit(FIVE_ASKS + [NEUTRAL])
        flag = flags["brevity-follow-ups"]
        self.assertEqual(flag["value"], "yes")
        self.assertEqual(flag["count"], 5)

    def test_five_inline_asks_order_an_automate_me_pass(self):
        _, flags = audit(FIVE_ASKS + [NEUTRAL])
        self.assertEqual(flags["intervention-must-automate"]["value"], "yes")

    def test_why_didnt_you_is_agent_blame(self):
        result, _ = audit(FIVE_ASKS)
        self.assertEqual(result["frustration"]["kinds"].get("agent-blame"), 2)

    def test_inline_automate_me_is_an_intervention_command(self):
        result, _ = audit(FIVE_ASKS)
        self.assertEqual(result["frustration"].get("intervention_commands"), {"/automate-me": 1})

    def test_open_a_file_request_stays_silent(self):
        result, flags = audit([NEUTRAL])
        self.assertEqual(flags["brevity-follow-ups"]["count"], 0)
        self.assertEqual(result["frustration"]["count"], 0)
        self.assertEqual(result["frustration"].get("intervention_command_count", 0), 0)

    def test_a_path_with_a_slash_word_is_not_a_diu_request(self):
        _, flags = audit(["read docs/diu/notes.md and the eli5x helper"])
        self.assertEqual(flags["brevity-follow-ups"]["count"], 0)


if __name__ == "__main__":
    unittest.main()
