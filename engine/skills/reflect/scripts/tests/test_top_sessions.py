#!/usr/bin/env python3
"""Fixture tests for top_sessions.py session coverage.

Run: python3 -m unittest discover -s engine/skills/reflect/scripts/tests -p "test_top_sessions.py"
(stdlib unittest only - no pytest in this environment)

Each test builds a throwaway HOME holding synthetic session trees shaped like
real ones, never a real user transcript. The claim under test: every session
subagent_cost.py can read is ranked, and no block drops a ranked session
without saying how many it dropped.
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS_DIR)

import subagent_cost  # noqa: E402
import top_sessions  # noqa: E402


def assistant_line(message_id, output_tokens):
    """One deduped assistant row carrying a usage snapshot."""
    return {
        "type": "assistant",
        "uuid": message_id + "-u1",
        "message": {
            "id": message_id,
            "model": "claude-sonnet-5",
            "usage": {
                "input_tokens": 0,
                "output_tokens": output_tokens,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
            "content": [{"type": "text", "text": "x"}],
        },
    }


def write_jsonl(path, rows):
    """Write rows as JSONL, creating parent directories."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


class ClaudeSessionCoverage(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.project_dir = os.path.join(self.home, ".claude", "projects", "-home-user-catstack")
        os.makedirs(self.project_dir)
        self.previous_home = os.environ.get("HOME")
        os.environ["HOME"] = self.home

    def tearDown(self):
        if self.previous_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.previous_home
        shutil.rmtree(self.home, ignore_errors=True)

    def build_session(self, session_id, own_tokens=0, subagent_tokens=0, own_transcript=True):
        """Create one session tree and return (transcript path, session dir)."""
        transcript_path = os.path.join(self.project_dir, session_id + ".jsonl")
        session_dir = os.path.join(self.project_dir, session_id)
        if own_transcript:
            write_jsonl(transcript_path, [assistant_line("parent-" + session_id, own_tokens)])
        if subagent_tokens:
            write_jsonl(
                os.path.join(session_dir, "subagents", "agent-a1.jsonl"),
                [assistant_line("child-" + session_id, subagent_tokens)],
            )
        return transcript_path, session_dir

    def run_main(self, *arguments):
        """Run top_sessions.main() with the given argv and return (stdout, stderr)."""
        captured_out, captured_err = io.StringIO(), io.StringIO()
        original_argv = sys.argv
        sys.argv = ["top_sessions.py", *arguments]
        try:
            with redirect_stdout(captured_out), redirect_stderr(captured_err):
                top_sessions.main()
        finally:
            sys.argv = original_argv
        return captured_out.getvalue(), captured_err.getvalue()

    @staticmethod
    def claude_block(output):
        """The CLAUDE block of one top_sessions.py run, header line first."""
        lines = output.splitlines()
        start = next(index for index, line in enumerate(lines) if "CLAUDE SESSIONS" in line)
        end = next(
            (index for index in range(start + 1, len(lines)) if lines[index].startswith("===")),
            len(lines),
        )
        return lines[start:end]

    def test_lists_a_session_with_its_own_transcript_and_subagents(self):
        transcript_path, _ = self.build_session("aaa", own_tokens=100, subagent_tokens=900)
        output, _ = self.run_main("5")
        block = self.claude_block(output)
        self.assertTrue(any(transcript_path in line for line in block), output)
        self.assertIn("own=100 subagents=900 (1 file(s))", output)
        self.assertIn("1,000", output)

    def test_lists_a_session_whose_own_transcript_is_gone(self):
        _, session_dir = self.build_session("bbb", subagent_tokens=900, own_transcript=False)

        readable = subagent_cost.reflect_pass_cost(session_dir)
        self.assertIsNone(readable["unchecked"])
        self.assertEqual(readable["total_tokens"], 900)

        output, _ = self.run_main("5")
        block = self.claude_block(output)
        self.assertTrue(
            any(session_dir in line for line in block),
            f"subagent_cost.py read {readable['total_tokens']} tokens from {session_dir} "
            f"but top_sessions.py listed no row for it:\n{output}",
        )
        self.assertIn("subagents=900", output)

    def test_header_names_how_many_ranked_sessions_were_not_listed(self):
        for index, tokens in enumerate((300, 200, 100)):
            self.build_session(f"ses{index}", own_tokens=tokens)
        output, _ = self.run_main("1")
        header = self.claude_block(output)[0]
        self.assertIn("1 of 3 ranked listed", header)
        self.assertIn("2 not listed", header)
        self.assertIn("3 ranked", self.overall_header(output))

    @staticmethod
    def overall_header(output):
        """The header line of the overall ranking block."""
        return next(line for line in output.splitlines() if "SESSIONS OVERALL" in line)

    def test_all_lists_every_ranked_session(self):
        paths = [self.build_session(f"ses{index}", own_tokens=100 * (index + 1))[0]
                 for index in range(3)]
        output, _ = self.run_main("1", "--all")
        header = self.claude_block(output)[0]
        self.assertIn("3 ranked, all listed", header)
        for path in paths:
            self.assertIn(path, output)

    def test_block_header_reports_a_full_block_as_all_listed(self):
        self.assertIn("all listed", top_sessions.block_header("TOP CLAUDE SESSIONS", 4, 4))
        self.assertIn(
            "2 not listed",
            top_sessions.block_header("TOP CLAUDE SESSIONS", 2, 4),
        )

    def test_session_paths_include_a_subagents_only_session_once(self):
        transcript_path, _ = self.build_session("aaa", own_tokens=10, subagent_tokens=10)
        _, orphan_dir = self.build_session("bbb", subagent_tokens=10, own_transcript=False)
        paths = top_sessions.claude_session_paths()
        self.assertEqual(sorted(paths), sorted([transcript_path, orphan_dir]))


if __name__ == "__main__":
    unittest.main()
