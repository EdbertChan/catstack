#!/usr/bin/env python3
"""Tests for reflect-on-thrash. Uses committed token_audit fixtures.

Run: python3 -m unittest discover -s hooks/reflect-on-thrash/tests -v
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(HOOKS_DIR))
FIXTURES = os.path.join(
    REPO_ROOT, "skills", "reflect", "scripts", "tests", "fixtures"
)
sys.path.insert(0, HOOKS_DIR)

import claude_stop_reflect  # noqa: E402
import cursor_session  # noqa: E402
import detect  # noqa: E402


def fixture(name: str) -> str:
    return os.path.join(FIXTURES, name)


def run_claude(payload: dict):
    err = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with redirect_stderr(err):
            try:
                claude_stop_reflect.main()
            except SystemExit as exc:
                return exc.code == 2, err.getvalue()
    return False, err.getvalue()


def run_cursor(payload: dict, argv: list[str] | None = None) -> dict:
    out = io.StringIO()
    args = ["cursor_session.py", *(argv or [])]
    with patch.object(sys, "argv", args):
        with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
            with redirect_stdout(out):
                cursor_session.main()
    return json.loads(out.getvalue() or "{}")


class TestThrashHits(unittest.TestCase):
    def test_clean_fixture_is_not_thrash(self):
        self.assertEqual(detect.thrash_hits(fixture("clean_efficient_session.jsonl")), [])

    def test_lookup_heavy_is_not_thrash(self):
        # Cheaper-model candidates only — not a reflect trigger.
        self.assertEqual(detect.thrash_hits(fixture("lookup_heavy_session.jsonl")), [])

    def test_thrash_fixture_hits(self):
        hits = detect.thrash_hits(fixture("token_thrash_session.jsonl"))
        self.assertTrue(hits)
        joined = " ".join(hits)
        self.assertIn("frustration-signals", joined)
        self.assertIn("no-verify-edit-streak", joined)

    def test_single_redundant_read_does_not_hit(self):
        # Threshold is 3; one re-read is not enough.
        path = os.path.join(tempfile.mkdtemp(), "one.jsonl")
        usage = {
            "input_tokens": 1,
            "output_tokens": 1,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }
        lines = []
        for i in range(2):
            lines.append(
                {
                    "type": "assistant",
                    "message": {
                        "id": f"m{i}",
                        "usage": usage,
                        "content": [
                            {
                                "type": "tool_use",
                                "id": f"t{i}",
                                "name": "Read",
                                "input": {"file_path": "/a.py", "offset": 1, "limit": 10},
                            }
                        ],
                    },
                }
            )
        with open(path, "w", encoding="utf-8") as handle:
            for line in lines:
                handle.write(json.dumps(line) + "\n")
        self.assertEqual(detect.thrash_hits(path), [])


class TestDecideOnce(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["REFLECT_ON_THRASH_STATE_DIR"] = self.tmp.name
        detect.STATE_DIR = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_thrash_defers_on_stop_then_delivers_once_on_session_end(self):
        path = fixture("token_thrash_session.jsonl")
        first = detect.decide({"transcript_path": path}, deliver=False)
        self.assertIsNone(first)
        self.assertTrue(detect.has_deferred(path))
        delivered = detect.decide({"transcript_path": path}, deliver=True)
        self.assertIsNotNone(delivered)
        self.assertIn("Read the reflect skill", delivered)
        self.assertIn(path, delivered)
        second = detect.decide({"transcript_path": path}, deliver=True)
        self.assertIsNone(second)

    def test_stop_hook_active_skips(self):
        path = fixture("token_thrash_session.jsonl")
        self.assertIsNone(
            detect.decide({"transcript_path": path, "stop_hook_active": True})
        )

    def test_clean_does_not_prompt(self):
        self.assertIsNone(
            detect.decide({"transcript_path": fixture("clean_efficient_session.jsonl")})
        )

    def test_user_already_said_reflect_skips(self):
        src = fixture("token_thrash_session.jsonl")
        path = os.path.join(self.tmp.name, "asked.jsonl")
        with open(src, encoding="utf-8") as handle:
            body = handle.read()
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
            handle.write(
                json.dumps(
                    {
                        "type": "user",
                        "message": {"role": "user", "content": "please /reflect this mess"},
                    }
                )
                + "\n"
            )
        self.assertTrue(detect.user_already_asked_reflect(path))
        self.assertIsNone(detect.decide({"transcript_path": path}))


class TestHarnessWrappers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["REFLECT_ON_THRASH_STATE_DIR"] = self.tmp.name
        detect.STATE_DIR = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_claude_does_not_block_on_thrash(self):
        blocked, err = run_claude(
            {"transcript_path": fixture("token_thrash_session.jsonl")}
        )
        self.assertFalse(blocked)
        self.assertEqual(err, "")

    def test_claude_allows_clean(self):
        blocked, err = run_claude(
            {"transcript_path": fixture("clean_efficient_session.jsonl")}
        )
        self.assertFalse(blocked)
        self.assertEqual(err, "")

    def test_cursor_stop_is_silent_on_thrash(self):
        body = run_cursor({"transcript_path": fixture("token_thrash_session.jsonl")})
        self.assertEqual(body.get("followup_message"), "")

    def test_cursor_session_end_followup_on_thrash(self):
        path = fixture("token_thrash_session.jsonl")
        run_cursor({"transcript_path": path})
        body = run_cursor({"transcript_path": path}, argv=["sessionEnd"])
        self.assertIn("reflect", body.get("followup_message", ""))

    def test_cursor_empty_on_clean(self):
        body = run_cursor({"transcript_path": fixture("clean_efficient_session.jsonl")})
        self.assertEqual(body.get("followup_message"), "")

    def test_malformed_stdin_fail_open(self):
        err = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("not-json")):
            with redirect_stderr(err):
                claude_stop_reflect.main()
        self.assertEqual(err.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
