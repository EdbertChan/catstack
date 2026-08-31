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


def no_verify_streak_path(directory: str) -> str:
    """Calm user + four edits, no test run — ordinary thrash, not intervention."""
    path = os.path.join(directory, "no-verify.jsonl")
    usage = {
        "input_tokens": 1,
        "output_tokens": 1,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    lines = [
        {"type": "user", "message": {"role": "user", "content": "please tweak the parser slightly"}},
    ]
    for i in range(4):
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
                            "name": "Edit",
                            "input": {
                                "file_path": "/repo/src/parse.py",
                                "old_string": f"v{i}",
                                "new_string": f"v{i + 1}",
                            },
                        }
                    ],
                },
            }
        )
    with open(path, "w", encoding="utf-8") as handle:
        for line in lines:
            handle.write(json.dumps(line) + "\n")
    return path


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
        self.assertEqual(detect.thrash_hits(fixture("lookup_heavy_session.jsonl")), [])

    def test_thrash_fixture_hits(self):
        hits = detect.thrash_hits(fixture("token_thrash_session.jsonl"))
        self.assertTrue(hits)
        joined = " ".join(hits)
        self.assertIn("frustration-signals", joined)
        self.assertIn("no-verify-edit-streak", joined)
        self.assertIn("intervention-must-automate", joined)
        self.assertTrue(detect.intervention_hit(hits))

    def test_codex_fixture_is_sniffed_and_routed_through_audit_codex(self):
        """Codex rollout JSONL (session_meta/turn_context/response_item/
        event_msg) is a disjoint shape from Claude's assistant+usage lines
        and Cursor's assistant-without-usage lines - verified against a real
        ~/.codex/sessions/**/*.jsonl rollout, not guessed."""
        path = fixture("codex_thrash_session.jsonl")
        self.assertEqual(detect.sniff_mode(path), "codex")
        hits = detect.thrash_hits(path)
        self.assertTrue(hits)
        joined = " ".join(hits)
        self.assertIn("frustration-signals", joined)
        self.assertIn("intervention-must-automate", joined)
        self.assertTrue(detect.intervention_hit(hits))

    def test_codex_clean_input_is_not_thrash(self):
        lines = [
            {"timestamp": "2026-08-27T10:00:00.000Z", "type": "session_meta", "payload": {}},
            {
                "timestamp": "2026-08-27T10:00:01.000Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "please add a health-check endpoint"}],
                },
            },
        ]
        path = os.path.join(tempfile.mkdtemp(), "codex-clean.jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            for line in lines:
                handle.write(json.dumps(line) + "\n")
        self.assertEqual(detect.sniff_mode(path), "codex")
        self.assertEqual(detect.thrash_hits(path), [])

    def test_codex_malformed_input_fails_open(self):
        path = os.path.join(tempfile.mkdtemp(), "codex-malformed.jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("not json at all\n")
            handle.write("{ still not json\n")
        self.assertEqual(detect.thrash_hits(path), [])

    def test_codex_missing_file_fails_open(self):
        self.assertEqual(detect.thrash_hits("/nonexistent/codex-rollout.jsonl"), [])

    def test_single_redundant_read_does_not_hit(self):
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

    def test_intervention_delivers_immediately_on_stop(self):
        path = fixture("token_thrash_session.jsonl")
        first = detect.decide({"transcript_path": path}, deliver=False)
        self.assertIsNotNone(first)
        self.assertIn("automate-me", first)
        self.assertIn("FAILURE", first)
        self.assertIn(path, first)
        self.assertFalse(detect.has_deferred(path))
        second = detect.decide({"transcript_path": path}, deliver=True)
        self.assertIsNone(second)

    def test_ordinary_thrash_defers_on_stop_then_delivers_once_on_session_end(self):
        path = no_verify_streak_path(self.tmp.name)
        hits = detect.thrash_hits(path)
        self.assertTrue(hits)
        self.assertFalse(detect.intervention_hit(hits))
        first = detect.decide({"transcript_path": path}, deliver=False)
        self.assertIsNone(first)
        self.assertTrue(detect.has_deferred(path))
        delivered = detect.decide({"transcript_path": path}, deliver=True)
        self.assertIsNotNone(delivered)
        self.assertIn("Read the reflect skill", delivered)
        self.assertNotIn("FAILURE", delivered)
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

    def test_claude_blocks_on_intervention(self):
        blocked, err = run_claude(
            {"transcript_path": fixture("token_thrash_session.jsonl")}
        )
        self.assertTrue(blocked)
        self.assertIn("automate-me", err)
        self.assertIn("FAILURE", err)

    def test_claude_does_not_block_on_ordinary_thrash(self):
        path = no_verify_streak_path(self.tmp.name)
        blocked, err = run_claude({"transcript_path": path})
        self.assertFalse(blocked)
        self.assertEqual(err, "")

    def test_claude_allows_clean(self):
        blocked, err = run_claude(
            {"transcript_path": fixture("clean_efficient_session.jsonl")}
        )
        self.assertFalse(blocked)
        self.assertEqual(err, "")

    def test_cursor_stop_followup_on_intervention(self):
        body = run_cursor({"transcript_path": fixture("token_thrash_session.jsonl")})
        self.assertIn("automate-me", body.get("followup_message", ""))

    def test_cursor_stop_is_silent_on_ordinary_thrash(self):
        path = no_verify_streak_path(self.tmp.name)
        body = run_cursor({"transcript_path": path})
        self.assertEqual(body.get("followup_message"), "")

    def test_cursor_session_end_followup_on_ordinary_thrash(self):
        path = no_verify_streak_path(self.tmp.name)
        run_cursor({"transcript_path": path})
        body = run_cursor({"transcript_path": path}, argv=["sessionEnd"])
        self.assertIn("reflect", body.get("followup_message", ""))
        self.assertNotIn("FAILURE", body.get("followup_message", ""))

    def test_cursor_session_end_silent_after_intervention_already_delivered(self):
        path = fixture("token_thrash_session.jsonl")
        first = run_cursor({"transcript_path": path})
        self.assertIn("automate-me", first.get("followup_message", ""))
        body = run_cursor({"transcript_path": path}, argv=["sessionEnd"])
        self.assertEqual(body.get("followup_message"), "")

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
