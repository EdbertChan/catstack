#!/usr/bin/env python3
"""Tests for the scratchpad-collision PreToolUse hook.

Run: python3 -m unittest discover -s engine/hooks/scratchpad-collision/tests -v

The fixture is the real collision: two agents in one session both wrote
`pr-body.md` in the shared scratchpad, and one PR was published with the other's
body. Agent A writes, agent B writes the same name seconds later (blocked),
A writes again (same writer, allowed), B writes a uniquely named file
(allowed), and after the window B may reuse the name.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOK_DIR)

import claude_pretooluse  # noqa: E402
import detect  # noqa: E402

AGENT_A = {"session_id": "sess-1", "transcript_path": "/x/agent-aaaa1111.jsonl"}
AGENT_B = {"session_id": "sess-1", "transcript_path": "/x/agent-bbbb2222.jsonl"}


def write(path, text="body"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)


def run_hook(agent, tool_name, tool_input):
    err = io.StringIO()
    payload = {**agent, "tool_name": tool_name, "tool_input": tool_input}
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with redirect_stderr(err):
            try:
                claude_pretooluse.main()
            except SystemExit as exc:
                return exc.code, err.getvalue()
    return 0, err.getvalue()


class ScratchpadCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.scratch = os.path.join(self.tmp.name, "scratchpad")
        os.makedirs(self.scratch)
        self.env = patch.dict(os.environ, {"CLAUDE_SCRATCHPAD": self.scratch})
        self.env.start()
        self.body = os.path.join(self.scratch, "pr-body.md")

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()


class TestBlocksCrossAgentCollision(ScratchpadCase):
    def test_blocks_second_agent_writing_same_name_within_window(self):
        code, _ = run_hook(AGENT_A, "Write", {"file_path": self.body, "content": "PR #7 body"})
        self.assertEqual(code, 0)
        write(self.body, "PR #7 body")
        code, err = run_hook(AGENT_B, "Write", {"file_path": self.body, "content": "PR #8 body"})
        self.assertEqual(code, 2)
        self.assertIn("another agent wrote pr-body.md", err)
        self.assertIn("uniquely named file", err)

    def test_blocks_bash_redirect_into_shared_file(self):
        run_hook(AGENT_A, "Bash", {"command": f"cat > {self.body} <<'EOF'\n## Summary\nEOF"})
        write(self.body)
        code, err = run_hook(AGENT_B, "Bash", {"command": f"gh pr view 7 --json body -q .body > {self.body}"})
        self.assertEqual(code, 2)
        self.assertIn("pr-body.md", err)

    def test_blocks_edit_by_other_agent_and_names_age(self):
        run_hook(AGENT_A, "Write", {"file_path": self.body, "content": "x"})
        write(self.body)
        old = time.time() - 30
        os.utime(self.body, (old, old))
        code, err = run_hook(AGENT_B, "Edit", {"file_path": self.body, "old_string": "x", "new_string": "y"})
        self.assertEqual(code, 2)
        self.assertIn("30 s ago", err)

    def test_blocks_under_real_scratchpad_path_pattern(self):
        path = "/private/tmp/claude-501/-Users-someone-repo/abcd/scratchpad/pr-body.md"
        self.assertEqual(detect.scratchpad_root(path), "/private/tmp/claude-501/-Users-someone-repo/abcd/scratchpad")
        self.assertIsNone(detect.scratchpad_root("/Users/someone/repo/pr-body.md"))


class TestAllowsSameWriterUniqueNamesAndOldFiles(ScratchpadCase):
    def test_allows_same_agent_rewriting_its_own_file(self):
        run_hook(AGENT_A, "Write", {"file_path": self.body, "content": "v1"})
        write(self.body, "v1")
        code, err = run_hook(AGENT_A, "Write", {"file_path": self.body, "content": "v2"})
        self.assertEqual(code, 0)
        self.assertEqual(err, "")

    def test_allows_uniquely_named_file_for_second_agent(self):
        run_hook(AGENT_A, "Write", {"file_path": self.body, "content": "PR #7"})
        write(self.body)
        other = os.path.join(self.scratch, "pr-body-8.md")
        code, _ = run_hook(AGENT_B, "Write", {"file_path": other, "content": "PR #8"})
        self.assertEqual(code, 0)

    def test_allows_after_window_passes(self):
        run_hook(AGENT_A, "Write", {"file_path": self.body, "content": "x"})
        write(self.body)
        old = time.time() - 11 * 60
        os.utime(self.body, (old, old))
        code, _ = run_hook(AGENT_B, "Write", {"file_path": self.body, "content": "y"})
        self.assertEqual(code, 0)

    def test_allows_new_file_and_unknown_writer(self):
        code, _ = run_hook(AGENT_B, "Write", {"file_path": self.body, "content": "first"})
        self.assertEqual(code, 0)
        write(os.path.join(self.scratch, "notes.md"))
        code, _ = run_hook(AGENT_B, "Write", {"file_path": os.path.join(self.scratch, "notes.md"), "content": "n"})
        self.assertEqual(code, 0)

    def test_allows_paths_outside_scratchpad(self):
        code, _ = run_hook(AGENT_B, "Write", {"file_path": os.path.join(self.tmp.name, "pr-body.md"), "content": "n"})
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, detect.SIDECAR)))

    def test_fails_open_on_garbage_stdin(self):
        err = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("not json")):
            with redirect_stderr(err):
                claude_pretooluse.main()
        self.assertEqual(err.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
