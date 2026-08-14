#!/usr/bin/env python3
"""Unit tests for token_audit.py and top_sessions.py.

Run: python3 -m unittest discover -s skills/reflect/scripts/tests -v
(stdlib unittest only - no pytest in this environment)

Fixtures are small synthetic JSONL built inline, not real user transcripts -
these must stay portable and never depend on data outside this repo.
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS_DIR)

import token_audit  # noqa: E402
import top_sessions  # noqa: E402


def write_jsonl(lines):
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for d in lines:
        f.write(json.dumps(d) + "\n")
    f.close()
    return f.name


def claude_assistant_line(mid, uuid, content_blocks, usage, model="claude-sonnet-5"):
    return {
        "type": "assistant",
        "uuid": uuid,
        "message": {"id": mid, "model": model, "usage": usage, "content": content_blocks},
    }


class TestClaudeDedup(unittest.TestCase):
    """The core bug this session fixed: Claude Code writes one JSONL line per
    content block (thinking/text/tool_use), but every block sharing a
    message.id carries the SAME usage snapshot. Summing raw lines
    double/triple counts - verified against a real transcript where 299 raw
    lines were only 141 unique messages."""

    def test_three_lines_same_message_id_counted_once(self):
        usage = {"input_tokens": 5, "output_tokens": 100, "cache_read_input_tokens": 200, "cache_creation_input_tokens": 10}
        lines = [
            claude_assistant_line("msg_1", "u1", [{"type": "thinking", "thinking": "..."}], usage),
            claude_assistant_line("msg_1", "u2", [{"type": "text", "text": "hi"}], usage),
            claude_assistant_line("msg_1", "u3", [{"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/a.py"}}], usage),
        ]
        path = write_jsonl(lines)
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                token_audit.audit_claude(path)
            out = buf.getvalue()
            self.assertIn("assistant turns: 1", out)
            self.assertIn("output=100", out)
            self.assertIn("cache_read=200", out)
        finally:
            os.unlink(path)

    def test_two_distinct_messages_both_counted(self):
        u1 = {"input_tokens": 1, "output_tokens": 50, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        u2 = {"input_tokens": 1, "output_tokens": 60, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        lines = [
            claude_assistant_line("msg_1", "u1", [{"type": "text", "text": "a"}], u1),
            claude_assistant_line("msg_2", "u2", [{"type": "text", "text": "b"}], u2),
        ]
        path = write_jsonl(lines)
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                token_audit.audit_claude(path)
            out = buf.getvalue()
            self.assertIn("assistant turns: 2", out)
            self.assertIn("output=110", out)
        finally:
            os.unlink(path)


class TestRedundantReads(unittest.TestCase):
    def test_read_immediately_followed_by_edit_is_not_thrash(self):
        # Read-before-Edit is required by tool semantics, not redundant.
        u = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        lines = [
            claude_assistant_line("m1", "u1", [{"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/a.py"}}], u),
            claude_assistant_line("m2", "u2", [{"type": "tool_use", "id": "t2", "name": "Edit", "input": {"file_path": "/a.py"}}], u),
            claude_assistant_line("m3", "u3", [{"type": "tool_use", "id": "t3", "name": "Read", "input": {"file_path": "/a.py"}}], u),
        ]
        path = write_jsonl(lines)
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                token_audit.audit_claude(path)
            self.assertIn("redundant re-reads (identical window): 0", buf.getvalue())
        finally:
            os.unlink(path)

    def test_read_twice_with_no_edit_is_thrash(self):
        u = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        lines = [
            claude_assistant_line("m1", "u1", [{"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/a.py"}}], u),
            claude_assistant_line("m2", "u2", [{"type": "tool_use", "id": "t2", "name": "Read", "input": {"file_path": "/a.py"}}], u),
        ]
        path = write_jsonl(lines)
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                token_audit.audit_claude(path)
            self.assertIn("redundant re-reads (identical window): 1", buf.getvalue())
        finally:
            os.unlink(path)

    def test_different_offset_windows_of_same_file_not_thrash(self):
        # Real bug found across 3 independent session reviews: comparing file_path
        # alone flagged normal windowed paging of a large file as "redundant".
        u = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        lines = [
            claude_assistant_line("m1", "u1", [{"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/big.py", "offset": 1, "limit": 200}}], u),
            claude_assistant_line("m2", "u2", [{"type": "tool_use", "id": "t2", "name": "Read", "input": {"file_path": "/big.py", "offset": 700, "limit": 90}}], u),
        ]
        path = write_jsonl(lines)
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                token_audit.audit_claude(path)
            self.assertIn("redundant re-reads (identical window): 0", buf.getvalue())
        finally:
            os.unlink(path)

    def test_identical_offset_window_read_twice_is_thrash(self):
        u = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        lines = [
            claude_assistant_line("m1", "u1", [{"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/big.py", "offset": 1, "limit": 200}}], u),
            claude_assistant_line("m2", "u2", [{"type": "tool_use", "id": "t2", "name": "Read", "input": {"file_path": "/big.py", "offset": 1, "limit": 200}}], u),
        ]
        path = write_jsonl(lines)
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                token_audit.audit_claude(path)
            self.assertIn("redundant re-reads (identical window): 1", buf.getvalue())
        finally:
            os.unlink(path)


class TestToolErrors(unittest.TestCase):
    def test_error_tool_result_is_flagged(self):
        u = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        lines = [
            claude_assistant_line("m1", "u1", [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "false"}}], u),
            {
                "type": "user",
                "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": "command failed"}]},
            },
        ]
        path = write_jsonl(lines)
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                token_audit.audit_claude(path)
            self.assertIn("tool errors: 1", buf.getvalue())
        finally:
            os.unlink(path)


class TestModelTierSavings(unittest.TestCase):
    def test_savings_uses_real_published_prices(self):
        # 1M output tokens: sonnet $15.00, haiku $5.00 -> $10 saved.
        actual, cheaper, saved = token_audit.model_tier_savings(1_000_000)
        self.assertAlmostEqual(actual, 15.00, places=2)
        self.assertAlmostEqual(cheaper, 5.00, places=2)
        self.assertAlmostEqual(saved, 10.00, places=2)

    def test_zero_tokens_zero_savings(self):
        actual, cheaper, saved = token_audit.model_tier_savings(0)
        self.assertEqual((actual, cheaper, saved), (0.0, 0.0, 0.0))


class TestCodexAudit(unittest.TestCase):
    def test_reads_token_count_events(self):
        lines = [
            {"type": "session_meta", "payload": {}},
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "total_token_usage": {"input_tokens": 100, "cached_input_tokens": 80, "output_tokens": 10, "total_tokens": 110},
                        "last_token_usage": {"input_tokens": 100, "cached_input_tokens": 80, "output_tokens": 10, "total_tokens": 110},
                    },
                },
            },
        ]
        path = write_jsonl(lines)
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                token_audit.audit_codex(path)
            out = buf.getvalue()
            self.assertIn("'total_tokens': 110", out)
        finally:
            os.unlink(path)


class TestOmpAudit(unittest.TestCase):
    def test_sums_usage_and_cost(self):
        lines = [
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "model": "gpt-5.5",
                    "usage": {"input": 10, "output": 5, "cacheRead": 20, "cacheWrite": 0, "totalTokens": 35, "cost": {"total": 0.01}},
                },
            },
        ]
        path = write_jsonl(lines)
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                token_audit.audit_omp(path)
            out = buf.getvalue()
            self.assertIn("total=35", out)
            self.assertIn("$0.0100", out)
        finally:
            os.unlink(path)


class TestTopSessionsScanFunctions(unittest.TestCase):
    """top_sessions.py has its own copy of the Claude dedup fix - test it
    independently so the two scripts can't silently drift apart."""

    def test_scan_claude_dedupes_by_message_id(self):
        usage = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 1, "cache_creation_input_tokens": 1}
        lines = [
            claude_assistant_line("m1", "u1", [{"type": "thinking"}], usage),
            claude_assistant_line("m1", "u2", [{"type": "text"}], usage),
        ]
        path = write_jsonl(lines)
        try:
            total = top_sessions.scan_claude(path)
            self.assertEqual(total, 4)  # 1+1+1+1, counted once not twice
        finally:
            os.unlink(path)

    def test_scan_codex_takes_final_cumulative_total(self):
        lines = [
            {"type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": {"total_tokens": 100}}}},
            {"type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": {"total_tokens": 250}}}},
        ]
        path = write_jsonl(lines)
        try:
            self.assertEqual(top_sessions.scan_codex(path), 250)
        finally:
            os.unlink(path)

    def test_scan_omp_sums_tokens_and_cost(self):
        lines = [
            {"type": "message", "message": {"usage": {"totalTokens": 30, "cost": {"total": 0.02}}}},
            {"type": "message", "message": {"usage": {"totalTokens": 20, "cost": {"total": 0.01}}}},
        ]
        path = write_jsonl(lines)
        try:
            total, cost = top_sessions.scan_omp(path)
            self.assertEqual(total, 50)
            self.assertAlmostEqual(cost, 0.03, places=4)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
