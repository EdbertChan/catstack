#!/usr/bin/env python3
"""Unit tests for build-the-lever inject hooks.

Run: python3 -m unittest discover -s engine/hooks/build-the-lever/tests -v
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
sys.path.insert(0, HOOKS_DIR)

import claude_posttooluse  # noqa: E402
import claude_prompt_submit  # noqa: E402
import codex_posttooluse  # noqa: E402
import codex_prompt_submit  # noqa: E402
import cursor_before_submit  # noqa: E402
import cursor_post_tool_use  # noqa: E402
import detect  # noqa: E402
import state  # noqa: E402


BULK_RENAME = "rename this config key across 40 files, and update every call site that reads the old name."
TYPO = "fix this one typo in the README — 'recieve' should be 'receive'."
COMMENT = "add a comment to Foo.ts"


def run_main(main, stdin_text: str) -> tuple[str, str, int]:
    out = io.StringIO()
    err = io.StringIO()
    code = 0
    with patch.object(sys, "stdin", io.StringIO(stdin_text)):
        with redirect_stdout(out), redirect_stderr(err):
            try:
                main()
            except SystemExit as exc:
                code = int(exc.code or 0)
    return out.getvalue(), err.getvalue(), code


def run_json(main, payload: dict) -> tuple[str, int]:
    out, _err, code = run_main(main, json.dumps(payload))
    return out, code


class BuildTheLeverCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        detect.STATE_DIR = self.tmp.name
        state.STATE_DIR = self.tmp.name

    def tearDown(self) -> None:
        self.tmp.cleanup()


class TestDetect(BuildTheLeverCase):
    def test_rename_across_40_files_fires(self) -> None:
        self.assertTrue(detect.is_bulk_work(BULK_RENAME))

    def test_every_call_site_fires(self) -> None:
        self.assertTrue(detect.is_bulk_work("update every call site that reads the old name"))

    def test_one_typo_does_not_fire(self) -> None:
        self.assertFalse(detect.is_bulk_work(TYPO))

    def test_add_comment_does_not_fire(self) -> None:
        self.assertFalse(detect.is_bulk_work(COMMENT))


class TestClaudePrompt(BuildTheLeverCase):
    def test_claude_prompt_injects_on_bulk(self) -> None:
        out, code = run_json(
            claude_prompt_submit.main,
            {"prompt": BULK_RENAME, "session_id": "bulk-1"},
        )
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertIn("build-the-lever", data["hookSpecificOutput"]["additionalContext"])
        self.assertNotIn("deny", json.dumps(data))

    def test_claude_prompt_prints_nothing_on_typo(self) -> None:
        out, code = run_json(
            claude_prompt_submit.main,
            {"prompt": TYPO, "session_id": "typo-1"},
        )
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")


class TestEdits(BuildTheLeverCase):
    def _write(self, session: str, path: str, tool: str = "Write") -> str:
        out, code = run_json(
            claude_posttooluse.main,
            {
                "session_id": session,
                "tool_name": tool,
                "tool_input": {"path": path},
            },
        )
        self.assertEqual(code, 0)
        return out

    def test_four_distinct_edits_fire(self) -> None:
        session = "edits-4"
        self.assertEqual(self._write(session, "a.ts").strip(), "")
        self.assertEqual(self._write(session, "b.ts").strip(), "")
        self.assertEqual(self._write(session, "c.ts").strip(), "")
        out = self._write(session, "d.ts")
        data = json.loads(out)
        self.assertIn("build-the-lever", data["hookSpecificOutput"]["additionalContext"])
        again = self._write(session, "e.ts")
        self.assertEqual(again.strip(), "")

    def test_three_edits_do_not_fire(self) -> None:
        session = "edits-3"
        self.assertEqual(self._write(session, "a.ts").strip(), "")
        self.assertEqual(self._write(session, "b.ts").strip(), "")
        self.assertEqual(self._write(session, "c.ts").strip(), "")

    def test_lever_script_write_prevents_edit_inject(self) -> None:
        session = "lever-1"
        self._write(session, "a.ts")
        self._write(session, "b.ts")
        self._write(session, "scripts/codemod.py")
        self.assertEqual(self._write(session, "c.ts").strip(), "")
        self.assertEqual(self._write(session, "d.ts").strip(), "")
        self.assertEqual(self._write(session, "e.ts").strip(), "")


class TestFailOpenAndNeverDeny(BuildTheLeverCase):
    def test_fail_open_on_bad_json(self) -> None:
        for main in (
            claude_prompt_submit.main,
            claude_posttooluse.main,
            cursor_before_submit.main,
            cursor_post_tool_use.main,
            codex_prompt_submit.main,
            codex_posttooluse.main,
        ):
            out, err, code = run_main(main, "not-json")
            self.assertEqual(code, 0, msg=f"{main} {err}")
            if main is cursor_before_submit.main:
                self.assertEqual(json.loads(out), {"continue": True})
            else:
                self.assertEqual(out.strip(), "")

    def test_wrappers_never_deny(self) -> None:
        payload = {"prompt": BULK_RENAME, "session_id": "deny-1"}
        for main in (claude_prompt_submit.main, codex_prompt_submit.main):
            out, code = run_json(main, payload)
            self.assertEqual(code, 0)
            dumped = out.lower()
            self.assertNotIn("deny", dumped)
            self.assertNotIn('"continue": false', dumped)
        out, code = run_json(cursor_before_submit.main, payload)
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data.get("continue"), True)
        post_out, post_code = run_json(
            cursor_post_tool_use.main,
            {"session_id": "deny-1", "tool_name": "Write", "tool_input": {"path": "x.ts"}},
        )
        self.assertEqual(post_code, 0)
        self.assertNotIn("deny", post_out.lower())
        self.assertNotIn('"continue": false', post_out.lower())
        self.assertIn("build-the-lever", json.loads(post_out)["additional_context"])


if __name__ == "__main__":
    unittest.main()
