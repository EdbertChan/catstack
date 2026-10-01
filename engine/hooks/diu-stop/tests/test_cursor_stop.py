#!/usr/bin/env python3
"""Cursor stop reads the last assistant text from the transcript."""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LLM_JUDGE_DIR = os.path.join(os.path.dirname(HOOKS_DIR), "llm-judge")
sys.path.insert(0, LLM_JUDGE_DIR)
sys.path.insert(0, HOOKS_DIR)

import cursor_stop_check  # noqa: E402
import judge  # noqa: E402
from diu_limit import WORD_LIMIT  # noqa: E402
from judge_test_base import JudgeTestCase  # noqa: E402

LONG_REPLY = " ".join(["plain"] * (WORD_LIMIT + 50))
SHORT_REPLY = " ".join(["plain"] * 26)


def _assistant(text, tool=False):
    content = []
    if tool:
        content.append({"type": "tool_use", "name": "Read", "input": {}})
    if text:
        content.append({"type": "text", "text": text})
    return {"role": "assistant", "message": {"content": content}}


def _write_transcript(folder, rows):
    path = os.path.join(folder, "session.jsonl")
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    return path


def _run(payload):
    out = io.StringIO()
    err = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with redirect_stdout(out):
            with redirect_stderr(err):
                try:
                    cursor_stop_check.main()
                except SystemExit as exc:
                    return exc.code, out.getvalue(), err.getvalue()
    return 0, out.getvalue(), err.getvalue()


class TestCursorStopTranscript(JudgeTestCase):
    def setUp(self):
        super().setUp()
        os.environ[judge.CHILD_ENV] = "1"
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _payload(self, path):
        return {"status": "completed", "loop_count": 0, "transcript_path": path}

    def test_long_transcript_reply_fires_word_limit_as_followup(self):
        path = _write_transcript(self.tmp.name, [
            {"role": "user", "message": {"content": [{"type": "text", "text": "go"}]}},
            _assistant(SHORT_REPLY),
            _assistant(LONG_REPLY, tool=True),
            {"type": "turn_ended", "status": "success"},
        ])
        code, stdout, _err = _run(self._payload(path))
        body = json.loads(stdout)
        self.assertEqual(0, code)
        self.assertEqual(["followup_message"], list(body))
        self.assertIn("Apply diu", body["followup_message"])
        self.assertIn(str(WORD_LIMIT + 50), body["followup_message"])
        self.assertNotIn("permission", body)

    def test_short_transcript_reply_stays_silent_on_word_limit(self):
        path = _write_transcript(self.tmp.name, [
            _assistant(LONG_REPLY),
            _assistant(SHORT_REPLY),
            _assistant("", tool=True),
            {"type": "turn_ended", "status": "success"},
        ])
        code, stdout, _err = _run(self._payload(path))
        self.assertEqual(0, code)
        self.assertEqual("{}\n", stdout)
        self.assertNotIn("Apply diu", stdout)

    def test_missing_transcript_does_not_pass_as_short_reply(self):
        for payload in (
            {"status": "completed", "loop_count": 0},
            {"status": "completed", "loop_count": 0, "transcript_path": "/no/such/transcript.jsonl"},
        ):
            with self.subTest(payload=payload):
                code, stdout, _err = _run(payload)
                body = json.loads(stdout)
                self.assertEqual(0, code)
                self.assertIn("not a short reply", body["followup_message"])
                self.assertNotEqual("{}\n", stdout)

    def test_unreadable_transcript_does_not_pass_as_short_reply(self):
        code, stdout, _err = _run(self._payload(self.tmp.name))
        body = json.loads(stdout)
        self.assertEqual(0, code)
        self.assertIn("could not be read", body["followup_message"])
        self.assertIn("not a short reply", body["followup_message"])
        self.assertNotIn("Apply diu", stdout)

    def test_role_under_message_only_does_not_pass_as_short_reply(self):
        path = _write_transcript(self.tmp.name, [
            {"message": {"role": "assistant", "content": [{"type": "text", "text": LONG_REPLY}]}},
        ])
        code, stdout, _err = _run(self._payload(path))
        body = json.loads(stdout)
        self.assertEqual(0, code)
        self.assertIn("not a short reply", body["followup_message"])
        self.assertNotIn("Apply diu", stdout)


if __name__ == "__main__":
    unittest.main()
