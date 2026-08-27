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


def claude_error_line(tool_use_id, content):
    return {
        "type": "user",
        "message": {"content": [{"type": "tool_result", "tool_use_id": tool_use_id, "is_error": True, "content": content}]},
    }


class TestRecurringFailureSignatures(unittest.TestCase):
    """Same-shaped failure repeating is the 'stuck on the same problem'
    signal - distinct from exact-duplicate tool calls, which the redundant-
    read detector already covers."""

    def test_same_error_text_three_times_is_flagged(self):
        u = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        lines = []
        for i in range(1, 4):
            tid = f"t{i}"
            lines.append(claude_assistant_line(f"m{i}", f"u{i}", [{"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": "pytest"}}], u))
            lines.append(claude_error_line(tid, "ModuleNotFoundError: No module named 'foo'"))
        path = write_jsonl(lines)
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                result = token_audit.audit_claude(path)
            self.assertIn("x3  Bash", buf.getvalue())
            self.assertEqual(result["n_recurring_failures"], 1)
        finally:
            os.unlink(path)

    def test_distinct_errors_not_flagged(self):
        u = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        lines = [
            claude_assistant_line("m1", "u1", [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "pytest"}}], u),
            claude_error_line("t1", "ModuleNotFoundError: No module named 'foo'"),
            claude_assistant_line("m2", "u2", [{"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "pytest"}}], u),
            claude_error_line("t2", "AssertionError: expected 1 got 2"),
        ]
        path = write_jsonl(lines)
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                result = token_audit.audit_claude(path)
            self.assertEqual(result["n_recurring_failures"], 0)
        finally:
            os.unlink(path)

    def test_user_rejection_message_excluded_from_recurrence(self):
        # A rejected tool use is the user redirecting the agent, not the
        # agent repeatedly failing at the same problem - must not count.
        u = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        rejection = "The user doesn't want to proceed with this tool use. The tool use was rejected"
        lines = [
            claude_assistant_line("m1", "u1", [{"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "/a.py"}}], u),
            claude_error_line("t1", rejection),
            claude_assistant_line("m2", "u2", [{"type": "tool_use", "id": "t2", "name": "Edit", "input": {"file_path": "/a.py"}}], u),
            claude_error_line("t2", rejection),
        ]
        path = write_jsonl(lines)
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                result = token_audit.audit_claude(path)
            self.assertEqual(result["n_recurring_failures"], 0)
        finally:
            os.unlink(path)


class TestEditStreaksWithoutVerification(unittest.TestCase):
    def test_streak_of_edits_with_no_verify_call_is_flagged(self):
        u = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        lines = [
            claude_assistant_line(f"m{i}", f"u{i}", [{"type": "tool_use", "id": f"t{i}", "name": "Edit", "input": {"file_path": "/a.py"}}], u)
            for i in range(1, 5)
        ]
        path = write_jsonl(lines)
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                result = token_audit.audit_claude(path)
            out = buf.getvalue()
            self.assertIn("/a.py: 4 edits in a row with no verification call in between", out)
            self.assertEqual(result["longest_edit_streak_no_verify"], 4)
            self.assertIn("verification calls found", out)
        finally:
            os.unlink(path)

    def test_verify_bash_call_resets_the_streak(self):
        u = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        lines = [
            claude_assistant_line("m1", "u1", [{"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "/a.py"}}], u),
            claude_assistant_line("m2", "u2", [{"type": "tool_use", "id": "t2", "name": "Edit", "input": {"file_path": "/a.py"}}], u),
            claude_assistant_line("m3", "u3", [{"type": "tool_use", "id": "t3", "name": "Bash", "input": {"command": "pytest -q"}}], u),
            claude_assistant_line("m4", "u4", [{"type": "tool_use", "id": "t4", "name": "Edit", "input": {"file_path": "/a.py"}}], u),
        ]
        path = write_jsonl(lines)
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                result = token_audit.audit_claude(path)
            out = buf.getvalue()
            self.assertEqual(result["longest_edit_streak_no_verify"], 2)
            self.assertIn("verification calls found (test/build/lint/typecheck-shaped Bash commands): 1", out)
            self.assertNotIn("edits in a row with no verification", out)  # below THRESH=3, not flagged
        finally:
            os.unlink(path)

    def test_non_verify_bash_call_does_not_reset_streak(self):
        u = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        lines = [
            claude_assistant_line("m1", "u1", [{"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "/a.py"}}], u),
            claude_assistant_line("m2", "u2", [{"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "ls -la"}}], u),
            claude_assistant_line("m3", "u3", [{"type": "tool_use", "id": "t3", "name": "Edit", "input": {"file_path": "/a.py"}}], u),
            claude_assistant_line("m4", "u4", [{"type": "tool_use", "id": "t4", "name": "Edit", "input": {"file_path": "/a.py"}}], u),
        ]
        path = write_jsonl(lines)
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                result = token_audit.audit_claude(path)
            self.assertEqual(result["longest_edit_streak_no_verify"], 3)
        finally:
            os.unlink(path)

    def test_direct_interpreter_run_of_edited_file_counts_as_verification(self):
        """Real reflect finding: a 9-edit streak on claude_session_cost.py was
        flagged even though every edit cluster was immediately followed by
        `python3 claude_session_cost.py ...` - a real feedback-loop check
        VERIFY_RE didn't recognize since it only matches test/build/lint
        commands, not direct interpreter execution of a one-off script."""
        u = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        lines = [
            claude_assistant_line("m1", "u1", [{"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "tools/claude_session_cost.py"}}], u),
            claude_assistant_line("m2", "u2", [{"type": "tool_use", "id": "t2", "name": "Edit", "input": {"file_path": "tools/claude_session_cost.py"}}], u),
            claude_assistant_line("m3", "u3", [{"type": "tool_use", "id": "t3", "name": "Bash", "input": {"command": "python3 tools/claude_session_cost.py ~/.claude/projects --top 5"}}], u),
            claude_assistant_line("m4", "u4", [{"type": "tool_use", "id": "t4", "name": "Edit", "input": {"file_path": "tools/claude_session_cost.py"}}], u),
        ]
        path = write_jsonl(lines)
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                result = token_audit.audit_claude(path)
            out = buf.getvalue()
            self.assertEqual(result["longest_edit_streak_no_verify"], 2)
            self.assertEqual(result["direct_run_verify_count"], 1)
            self.assertIn("verification calls found (direct execution of the just-edited file", out)
        finally:
            os.unlink(path)

    def test_bare_dot_slash_run_of_edited_file_counts_as_verification(self):
        u = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        lines = [
            claude_assistant_line("m1", "u1", [{"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "run-all.sh"}}], u),
            claude_assistant_line("m2", "u2", [{"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "./run-all.sh"}}], u),
        ]
        path = write_jsonl(lines)
        try:
            with redirect_stdout(io.StringIO()):
                result = token_audit.audit_claude(path)
            self.assertEqual(result["direct_run_verify_count"], 1)
            self.assertEqual(result["longest_edit_streak_no_verify"], 1)
        finally:
            os.unlink(path)

    def test_running_a_different_file_does_not_verify_the_edited_one(self):
        u = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        lines = [
            claude_assistant_line("m1", "u1", [{"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "a.py"}}], u),
            claude_assistant_line("m2", "u2", [{"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "python3 b.py"}}], u),
            claude_assistant_line("m3", "u3", [{"type": "tool_use", "id": "t3", "name": "Edit", "input": {"file_path": "a.py"}}], u),
        ]
        path = write_jsonl(lines)
        try:
            with redirect_stdout(io.StringIO()):
                result = token_audit.audit_claude(path)
            self.assertEqual(result["direct_run_verify_count"], 0)
            self.assertEqual(result["longest_edit_streak_no_verify"], 2)
        finally:
            os.unlink(path)


class TestToolErrorBreakdown(unittest.TestCase):
    """Backlog item from a real reflect run: bucket tool errors by tool and
    by file so a session with many failures shows where they concentrated,
    not just a flat count."""

    def test_breakdown_by_tool_and_file(self):
        u = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        lines = [
            claude_assistant_line("m1", "u1", [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "false"}}], u),
            claude_error_line("t1", "boom"),
            claude_assistant_line("m2", "u2", [{"type": "tool_use", "id": "t2", "name": "Edit", "input": {"file_path": "/a.py"}}], u),
            claude_error_line("t2", "old_string not found"),
            claude_assistant_line("m3", "u3", [{"type": "tool_use", "id": "t3", "name": "Edit", "input": {"file_path": "/a.py"}}], u),
            claude_error_line("t3", "old_string not found again"),
        ]
        path = write_jsonl(lines)
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                token_audit.audit_claude(path)
            out = buf.getvalue()
            self.assertIn("-- tool errors by tool --", out)
            self.assertIn("Edit: 2", out)
            self.assertIn("Bash: 1", out)
            self.assertIn("-- tool errors by file --", out)
            self.assertIn("/a.py: 2", out)
        finally:
            os.unlink(path)

    def test_no_breakdown_section_when_no_errors(self):
        u = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        lines = [claude_assistant_line("m1", "u1", [{"type": "text", "text": "hi"}], u)]
        path = write_jsonl(lines)
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                token_audit.audit_claude(path)
            self.assertNotIn("-- tool errors by tool --", buf.getvalue())
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

    def test_read_then_edit_same_message_id_is_not_lookup_only(self):
        """Claude Code splits one turn across JSONL lines. Read on line 1 and
        Edit on line 2 of the same message.id must not count as a model-tier
        candidate — found by e2e clean_efficient_session fixture."""
        u = {"input_tokens": 1, "output_tokens": 80, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        lines = [
            claude_assistant_line("msg_1", "u1", [{"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/a.py"}}], u),
            claude_assistant_line("msg_1", "u2", [{"type": "tool_use", "id": "t2", "name": "Edit", "input": {"file_path": "/a.py"}}], u),
        ]
        path = write_jsonl(lines)
        try:
            with redirect_stdout(io.StringIO()):
                result = token_audit.audit_claude(path)
            flags = {fl["name"]: fl for fl in result["flags"]}
            self.assertEqual(flags["model-tier-candidates"]["value"], "no")
            self.assertEqual(flags["model-tier-candidates"]["count"], 0)
        finally:
            os.unlink(path)


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

    def test_out_writes_totals_json(self):
        lines = [
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "total_token_usage": {
                            "input_tokens": 100,
                            "cached_input_tokens": 80,
                            "output_tokens": 10,
                            "total_tokens": 110,
                        },
                        "last_token_usage": {
                            "input_tokens": 100,
                            "cached_input_tokens": 80,
                            "output_tokens": 10,
                            "total_tokens": 110,
                        },
                    },
                },
            },
        ]
        path = write_jsonl(lines)
        out = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        out.close()
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                result = token_audit.audit_codex(path, out_path=out.name)
            with open(out.name) as f:
                report = json.load(f)
            self.assertEqual(report["totals"]["total"], 110)
            self.assertEqual(report["totals"]["cached_input"], 80)
            self.assertEqual(result["total"], 110)
            self.assertIn(out.name, buf.getvalue())
            self.assertNotIn("per-turn growth", buf.getvalue())
        finally:
            os.unlink(path)
            os.unlink(out.name)


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


def omp_assistant_line(content_blocks, usage=None):
    msg = {"role": "assistant", "content": content_blocks}
    if usage is not None:
        msg["usage"] = usage
    return {"type": "message", "message": msg}


def omp_tool_result_line(call_id, tool_name, is_error=False):
    return {
        "type": "message",
        "message": {"role": "toolResult", "toolCallId": call_id, "toolName": tool_name, "isError": is_error, "content": []},
    }


class TestOmpThrashDetection(unittest.TestCase):
    """Verified against a real OMP session before writing: `read`/`write` name
    the file in arguments.path; `edit` embeds it in an apple-patch header
    inside arguments.input (`[/path/to/file.ts#anchor]`)."""

    def test_read_twice_no_edit_is_redundant(self):
        lines = [
            omp_assistant_line([{"type": "toolCall", "id": "c1", "name": "read", "arguments": {"path": "/a.ts"}}]),
            omp_assistant_line([{"type": "toolCall", "id": "c2", "name": "read", "arguments": {"path": "/a.ts"}}]),
        ]
        path = write_jsonl(lines)
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                token_audit.audit_omp(path)
            self.assertIn("redundant re-reads: 1", buf.getvalue())
        finally:
            os.unlink(path)

    def test_write_between_reads_clears_redundant_flag(self):
        lines = [
            omp_assistant_line([{"type": "toolCall", "id": "c1", "name": "read", "arguments": {"path": "/a.ts"}}]),
            omp_assistant_line([{"type": "toolCall", "id": "c2", "name": "write", "arguments": {"path": "/a.ts", "content": "x"}}]),
            omp_assistant_line([{"type": "toolCall", "id": "c3", "name": "read", "arguments": {"path": "/a.ts"}}]),
        ]
        path = write_jsonl(lines)
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                token_audit.audit_omp(path)
            self.assertIn("redundant re-reads: 0", buf.getvalue())
        finally:
            os.unlink(path)

    def test_edit_path_extracted_from_patch_header(self):
        edit_input = "*** Begin Patch\n[/src/main.ts#E1]\ninsert after block 1:\n+x\n"
        lines = [
            omp_assistant_line([{"type": "toolCall", "id": "c1", "name": "read", "arguments": {"path": "/src/main.ts"}}]),
            omp_assistant_line([{"type": "toolCall", "id": "c2", "name": "edit", "arguments": {"input": edit_input}}]),
            omp_assistant_line([{"type": "toolCall", "id": "c3", "name": "read", "arguments": {"path": "/src/main.ts"}}]),
        ]
        path = write_jsonl(lines)
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                token_audit.audit_omp(path)
            # the edit's path was correctly parsed from the patch header, so the
            # second read is NOT flagged as redundant (an edit happened in between)
            self.assertIn("redundant re-reads: 0", buf.getvalue())
        finally:
            os.unlink(path)

    def test_is_error_tool_result_counted(self):
        lines = [
            omp_assistant_line([{"type": "toolCall", "id": "c1", "name": "bash", "arguments": {"command": "false"}}]),
            omp_tool_result_line("c1", "bash", is_error=True),
        ]
        path = write_jsonl(lines)
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                token_audit.audit_omp(path)
            self.assertIn("tool errors: 1", buf.getvalue())
        finally:
            os.unlink(path)

    def test_non_error_tool_result_not_counted(self):
        lines = [
            omp_assistant_line([{"type": "toolCall", "id": "c1", "name": "bash", "arguments": {"command": "true"}}]),
            omp_tool_result_line("c1", "bash", is_error=False),
        ]
        path = write_jsonl(lines)
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                token_audit.audit_omp(path)
            self.assertIn("tool errors: 0", buf.getvalue())
        finally:
            os.unlink(path)


class TestParseTopBlock(unittest.TestCase):
    def test_parses_rows_from_own_output_format(self):
        text = (
            "scanning 3 claude, 0 codex, 0 omp files\n"
            "done in 1s, 3 sessions with usage data\n"
            "\n=== TOP 12 SESSIONS OVERALL (by total tokens) ===\n"
            "     1,500,000  [claude]  /a/one.jsonl\n"
            "       500,000  [omp]  /a/two.jsonl  ($1.23 OMP-reported)\n"
            "\n=== TOP 3 CLAUDE SESSIONS ===\n"
            "     1,500,000  /a/one.jsonl\n"
        )
        rows = top_sessions.parse_top_block(text)
        self.assertEqual(rows, [
            (1_500_000, "claude", "/a/one.jsonl"),
            (500_000, "omp", "/a/two.jsonl"),
        ])

    def test_empty_text_returns_no_rows(self):
        self.assertEqual(top_sessions.parse_top_block(""), [])


class TestMergeCrossMachine(unittest.TestCase):
    def test_dedupes_two_targets_sharing_one_hostname(self):
        # Real bug found in production: two SSH config entries (remote_1,
        # remote_2) resolved to the identical physical host.
        remote_text = (
            "HOSTNAME=box-a\n"
            "=== TOP 4 SESSIONS OVERALL (by total tokens) ===\n"
            "       900,000  [claude]  /home/invoker/x.jsonl\n"
        )
        remote_outputs = {
            "remote_1": remote_text,
            "remote_2": remote_text,  # same HOSTNAME line -> must be deduped
        }
        local_text = (
            "=== TOP 4 SESSIONS OVERALL (by total tokens) ===\n"
            "     2,000,000  [claude]  /Users/me/a.jsonl\n"
        )
        merged = top_sessions.merge_cross_machine(local_text, remote_outputs)
        targets = [r["target"] for r in merged]
        self.assertEqual(targets.count("remote_1"), 1)
        self.assertEqual(targets.count("remote_2"), 0)
        self.assertEqual(len(merged), 2)

    def test_merged_list_sorted_descending_by_tokens(self):
        remote_outputs = {
            "remote_1": (
                "HOSTNAME=box-a\n"
                "=== TOP 4 SESSIONS OVERALL (by total tokens) ===\n"
                "       900,000  [claude]  /home/invoker/x.jsonl\n"
            ),
        }
        local_text = (
            "=== TOP 4 SESSIONS OVERALL (by total tokens) ===\n"
            "     2,000,000  [claude]  /Users/me/a.jsonl\n"
            "       100,000  [claude]  /Users/me/b.jsonl\n"
        )
        merged = top_sessions.merge_cross_machine(local_text, remote_outputs)
        self.assertEqual([r["tokens"] for r in merged], [2_000_000, 900_000, 100_000])
        self.assertEqual(merged[0]["target"], "local")
        self.assertEqual(merged[1]["hostname"], "box-a")


class TestRunAudits(unittest.TestCase):
    def test_runs_claude_and_omp_audits_and_returns_text_per_path(self):
        u = {"input_tokens": 1, "output_tokens": 5, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        claude_path = write_jsonl([claude_assistant_line("m1", "u1", [{"type": "text", "text": "hi"}], u)])
        omp_path = write_jsonl([
            {"type": "message", "message": {"role": "assistant", "usage": {"input": 1, "output": 2, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 3, "cost": {"total": 0.001}}}},
        ])
        try:
            results = top_sessions.run_audits([("claude", claude_path), ("omp", omp_path)])
            self.assertIn("output=5", results[claude_path])
            self.assertIn("total=3", results[omp_path])
        finally:
            os.unlink(claude_path)
            os.unlink(omp_path)

    def test_writes_ranked_files_when_out_dir_given(self):
        u = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        path = write_jsonl([claude_assistant_line("m1", "u1", [{"type": "text", "text": "hi"}], u)])
        out_dir = tempfile.mkdtemp()
        try:
            top_sessions.run_audits([("claude", path)], out_dir=out_dir)
            written = os.path.join(out_dir, "rank0_claude.txt")
            self.assertTrue(os.path.exists(written))
            with open(written) as f:
                self.assertIn("assistant turns: 1", f.read())
        finally:
            os.unlink(path)
            for f in os.listdir(out_dir):
                os.unlink(os.path.join(out_dir, f))
            os.rmdir(out_dir)

    def test_unknown_kind_reported_as_error_not_raised(self):
        results = top_sessions.run_audits([("bogus", "/nonexistent.jsonl")])
        self.assertIn("ERROR", results["/nonexistent.jsonl"])


class TestOutFlags(unittest.TestCase):
    """--out writes named yes/no flags with rationales (judge shape), not prose."""

    FLAG_NAMES = {
        "model-tier-candidates",
        "redundant-reads",
        "recurring-failure-signatures",
        "no-verify-edit-streak",
        "cache-creation-spikes",
        "frustration-signals",
        "intervention-must-automate",
    }

    def _flag_by_name(self, report, name):
        for fl in report["flags"]:
            if fl["name"] == name:
                return fl
        self.fail(f"flag {name!r} missing from {report['flags']}")

    def test_out_writes_all_named_flags(self):
        u = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        lines = [
            claude_assistant_line("m1", "u1", [{"type": "text", "text": "hi"}], u),
        ]
        path = write_jsonl(lines)
        out = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        out.close()
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                result = token_audit.audit_claude(path, out_path=out.name)
            with open(out.name) as f:
                report = json.load(f)
            names = {fl["name"] for fl in report["flags"]}
            self.assertEqual(names, self.FLAG_NAMES)
            for fl in report["flags"]:
                self.assertIn(fl["value"], ("yes", "no"))
                self.assertIsInstance(fl["count"], int)
                self.assertTrue(fl["rationale"])
            # Quiet stdout: short summary, not the prose dump
            out_text = buf.getvalue()
            self.assertIn(out.name, out_text)
            self.assertNotIn("redundant re-reads (identical window)", out_text)
            self.assertEqual(result["flags"], report["flags"])
            self.assertIn("n_recurring_failures", report["totals"])
            self.assertIn("longest_edit_streak_no_verify", report["totals"])
        finally:
            os.unlink(path)
            os.unlink(out.name)

    def test_redundant_reads_flag_yes(self):
        u = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        lines = [
            claude_assistant_line("m1", "u1", [{"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/a.py", "offset": 1, "limit": 10}}], u),
            claude_assistant_line("m2", "u2", [{"type": "tool_use", "id": "t2", "name": "Read", "input": {"file_path": "/a.py", "offset": 1, "limit": 10}}], u),
        ]
        path = write_jsonl(lines)
        out = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        out.close()
        try:
            with redirect_stdout(io.StringIO()):
                token_audit.audit_claude(path, out_path=out.name)
            with open(out.name) as f:
                report = json.load(f)
            fl = self._flag_by_name(report, "redundant-reads")
            self.assertEqual(fl["value"], "yes")
            self.assertEqual(fl["count"], 1)
        finally:
            os.unlink(path)
            os.unlink(out.name)

    def test_recurring_failure_signatures_flag_yes(self):
        u = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        lines = []
        for i in range(1, 4):
            tid = f"t{i}"
            lines.append(claude_assistant_line(f"m{i}", f"u{i}", [{"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": "pytest"}}], u))
            lines.append(claude_error_line(tid, "ModuleNotFoundError: No module named 'foo'"))
        path = write_jsonl(lines)
        out = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        out.close()
        try:
            with redirect_stdout(io.StringIO()):
                token_audit.audit_claude(path, out_path=out.name)
            with open(out.name) as f:
                report = json.load(f)
            fl = self._flag_by_name(report, "recurring-failure-signatures")
            self.assertEqual(fl["value"], "yes")
            self.assertEqual(fl["count"], 1)
        finally:
            os.unlink(path)
            os.unlink(out.name)

    def test_no_verify_edit_streak_flag_yes(self):
        u = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        lines = [
            claude_assistant_line(f"m{i}", f"u{i}", [{"type": "tool_use", "id": f"t{i}", "name": "Edit", "input": {"file_path": "/a.py"}}], u)
            for i in range(1, 5)
        ]
        path = write_jsonl(lines)
        out = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        out.close()
        try:
            with redirect_stdout(io.StringIO()):
                token_audit.audit_claude(path, out_path=out.name)
            with open(out.name) as f:
                report = json.load(f)
            fl = self._flag_by_name(report, "no-verify-edit-streak")
            self.assertEqual(fl["value"], "yes")
            self.assertEqual(fl["count"], 4)
        finally:
            os.unlink(path)
            os.unlink(out.name)

    def test_model_tier_candidates_flag_yes(self):
        u = {"input_tokens": 1, "output_tokens": 50, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        lines = [
            claude_assistant_line("m1", "u1", [{"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/a.py"}}], u),
        ]
        path = write_jsonl(lines)
        out = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        out.close()
        try:
            with redirect_stdout(io.StringIO()):
                token_audit.audit_claude(path, out_path=out.name)
            with open(out.name) as f:
                report = json.load(f)
            fl = self._flag_by_name(report, "model-tier-candidates")
            self.assertEqual(fl["value"], "yes")
            self.assertEqual(fl["count"], 1)
        finally:
            os.unlink(path)
            os.unlink(out.name)

    def test_cache_creation_spikes_flag_yes(self):
        # Several small creations set a low median; one huge spike clears
        # max(50k, 5x median).
        small = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 1000}
        big = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 100_000}
        lines = [
            claude_assistant_line("m1", "u1", [{"type": "text", "text": "a"}], small),
            claude_assistant_line("m2", "u2", [{"type": "text", "text": "b"}], small),
            claude_assistant_line("m3", "u3", [{"type": "text", "text": "c"}], small),
            claude_assistant_line("m4", "u4", [{"type": "text", "text": "d"}], big),
        ]
        path = write_jsonl(lines)
        out = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        out.close()
        try:
            with redirect_stdout(io.StringIO()):
                token_audit.audit_claude(path, out_path=out.name)
            with open(out.name) as f:
                report = json.load(f)
            fl = self._flag_by_name(report, "cache-creation-spikes")
            self.assertEqual(fl["value"], "yes")
            self.assertGreaterEqual(fl["count"], 1)
        finally:
            os.unlink(path)
            os.unlink(out.name)

    def test_parse_argv_accepts_out_before_or_after_path(self):
        mode, path, out = token_audit._parse_argv(["token_audit.py", "claude", "s.jsonl", "--out", "/tmp/a.json"])
        self.assertEqual((mode, path, out), ("claude", "s.jsonl", "/tmp/a.json"))
        mode, path, out = token_audit._parse_argv(["token_audit.py", "claude", "--out", "/tmp/b.json", "s.jsonl"])
        self.assertEqual((mode, path, out), ("claude", "s.jsonl", "/tmp/b.json"))


def claude_user_text_line(text, ts=None):
    d = {"type": "user", "message": {"role": "user", "content": text}}
    if ts:
        d["timestamp"] = ts
    return d


class TestFrustrationSignals(unittest.TestCase):
    """Frustration-lens feed: mechanical tone-spike detection over HUMAN user
    messages only. Added after a real session where 13/56 user messages were
    all-caps demands, profanity, or verbatim repeats, and the reflect
    synthesis ranked root causes by frustration caused, not tokens burned."""

    def test_detects_each_signal_kind_and_counts_interruptions(self):
        usage = {"input_tokens": 1, "output_tokens": 1}
        lines = [
            claude_user_text_line("thanks, looks good", ts="2026-08-18T02:00:00Z"),
            claude_user_text_line("WHERE IS MY DIGITAL TWIN? WHAT THE FUCK IS GOING ON", ts="2026-08-18T02:30:00Z"),
            claude_user_text_line("i told you to have it ready", ts="2026-08-18T02:31:00Z"),
            claude_user_text_line("am i in a zoom meeting at all???", ts="2026-08-18T02:32:00Z"),
            claude_user_text_line("please fix the audio now", ts="2026-08-18T02:33:00Z"),
            claude_user_text_line("please fix the audio now", ts="2026-08-18T02:35:00Z"),
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "text", "text": "[Request interrupted by user]"}]}},
            claude_assistant_line("m1", "u1", [{"type": "text", "text": "ok"}], usage),
        ]
        path = write_jsonl(lines)
        try:
            with redirect_stdout(io.StringIO()):
                result = token_audit.audit_claude(path)
            fr = result["frustration"]
            self.assertEqual(fr["n_user_messages"], 6)
            self.assertEqual(fr["interruptions"], 1)
            kinds = {k for f in fr["flagged"] for k in f["kinds"]}
            for expected in ("allcaps", "profanity", "told-you", "multi-question-marks", "verbatim-repeat"):
                self.assertIn(expected, kinds)
            self.assertEqual(fr["count"], 4)
            self.assertEqual(fr["peak_window"], ["2026-08-18T02:30:00Z", "2026-08-18T02:35:00Z"])
            flag = next(f for f in result["flags"] if f["name"] == "frustration-signals")
            self.assertEqual(flag["value"], "yes")
            self.assertEqual(flag["count"], 4)
        finally:
            os.unlink(path)

    def test_tool_results_never_count_as_user_messages(self):
        usage = {"input_tokens": 1, "output_tokens": 1}
        lines = [
            claude_assistant_line("m1", "u1", [
                {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}], usage),
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1",
                 "content": "TOTAL FAILURE ??? WHAT THE FUCK IS THIS OUTPUT"}]}},
        ]
        path = write_jsonl(lines)
        try:
            with redirect_stdout(io.StringIO()):
                result = token_audit.audit_claude(path)
            self.assertEqual(result["frustration"]["n_user_messages"], 0)
            self.assertEqual(result["frustration"]["count"], 0)
        finally:
            os.unlink(path)


    def test_system_injected_user_turns_are_excluded(self):
        usage = {"input_tokens": 1, "output_tokens": 1}
        lines = [
            claude_user_text_line("<task-notification>\n<task-id>x</task-id> you are thrashing</task-notification>"),
            claude_user_text_line("<command-message>reflect</command-message>"),
            claude_user_text_line("This session is being continued from a previous conversation that ran out of context. WHAT THE FUCK"),
            claude_user_text_line("a genuine human message"),
            claude_assistant_line("m1", "u1", [{"type": "text", "text": "ok"}], usage),
        ]
        path = write_jsonl(lines)
        try:
            with redirect_stdout(io.StringIO()):
                result = token_audit.audit_claude(path)
            self.assertEqual(result["frustration"]["n_user_messages"], 1)
            self.assertEqual(result["frustration"]["count"], 0)
        finally:
            os.unlink(path)

    def test_ismeta_rows_are_excluded_even_without_a_matching_prefix(self):
        """Stop-hook feedback text ("Stop hook feedback:\\n[python3 ...]") and
        /loop wakeup re-injections carry isMeta:true but their text matches no
        SYSTEM_INJECTED_PREFIXES entry, so before this fix they were counted as
        the human repeating themselves - the exact false positive that made
        token_audit.py flag intervention-must-automate for a verbatim /loop
        re-send instead of a real user repeat."""
        usage = {"input_tokens": 1, "output_tokens": 1}

        def ismeta_line(text):
            return {"type": "user", "isMeta": True, "message": {"role": "user", "content": text}}

        lines = [
            ismeta_line("Stop hook feedback:\n[python3 $HOME/.claude/hooks/diu-stop/claude_stop_check.py]: Apply diu: 373 words, over the 150-word guideline."),
            ismeta_line("Check whether the isolated Invoker window has rendered yet, screenshot it, quit it, and finalize PR2's Visual Proof section."),
            ismeta_line("Check whether the isolated Invoker window has rendered yet, screenshot it, quit it, and finalize PR2's Visual Proof section."),
            claude_user_text_line("a genuine human message"),
            claude_assistant_line("m1", "u1", [{"type": "text", "text": "ok"}], usage),
        ]
        path = write_jsonl(lines)
        try:
            with redirect_stdout(io.StringIO()):
                result = token_audit.audit_claude(path)
            self.assertEqual(result["frustration"]["n_user_messages"], 1)
            self.assertEqual(result["frustration"]["count"], 0)
        finally:
            os.unlink(path)
    def test_repeat_outside_ten_minute_window_not_flagged(self):
        usage = {"input_tokens": 1, "output_tokens": 1}
        lines = [
            claude_user_text_line("please fix the audio now", ts="2026-08-18T02:00:00Z"),
            claude_user_text_line("please fix the audio now", ts="2026-08-18T02:20:00Z"),
            claude_assistant_line("m1", "u1", [{"type": "text", "text": "ok"}], usage),
        ]
        path = write_jsonl(lines)
        try:
            with redirect_stdout(io.StringIO()):
                result = token_audit.audit_claude(path)
            self.assertEqual(result["frustration"]["count"], 0)
        finally:
            os.unlink(path)

    def test_agent_blame_and_same_type_must_automate(self):
        """You-messed-up is agent-blame; product 'the ui is messed up' is not.
        Two told-yous fire intervention-must-automate; one told-you does not."""
        usage = {"input_tokens": 1, "output_tokens": 1}
        two_told = [
            claude_user_text_line("i told you to add a test", ts="2026-08-24T01:00:00Z"),
            claude_user_text_line("i asked you not to skip e2e", ts="2026-08-24T01:01:00Z"),
            claude_assistant_line("m1", "u1", [{"type": "text", "text": "ok"}], usage),
        ]
        path = write_jsonl(two_told)
        try:
            with redirect_stdout(io.StringIO()):
                result = token_audit.audit_claude(path)
            kinds = {k for f in result["frustration"]["flagged"] for k in f["kinds"]}
            self.assertIn("told-you", kinds)
            flag = next(f for f in result["flags"] if f["name"] == "intervention-must-automate")
            self.assertEqual(flag["value"], "yes")
        finally:
            os.unlink(path)

        one_told = [
            claude_user_text_line("i told you to add a test", ts="2026-08-24T01:00:00Z"),
            claude_assistant_line("m1", "u1", [{"type": "text", "text": "ok"}], usage),
        ]
        path = write_jsonl(one_told)
        try:
            with redirect_stdout(io.StringIO()):
                result = token_audit.audit_claude(path)
            flag = next(f for f in result["flags"] if f["name"] == "intervention-must-automate")
            self.assertEqual(flag["value"], "no")
        finally:
            os.unlink(path)

        blame_vs_product = [
            claude_user_text_line("you messed up the merge", ts="2026-08-24T01:00:00Z"),
            claude_user_text_line("ok so the ui is just messed up then", ts="2026-08-24T01:01:00Z"),
            claude_user_text_line("I said the file is in src/", ts="2026-08-24T01:02:00Z"),
            claude_assistant_line("m1", "u1", [{"type": "text", "text": "ok"}], usage),
        ]
        path = write_jsonl(blame_vs_product)
        try:
            with redirect_stdout(io.StringIO()):
                result = token_audit.audit_claude(path)
            kinds = {k for f in result["frustration"]["flagged"] for k in f["kinds"]}
            self.assertIn("agent-blame", kinds)
            excerpts = " ".join(f["excerpt"] for f in result["frustration"]["flagged"])
            self.assertIn("you messed up", excerpts)
            self.assertNotIn("ui is just messed up", excerpts)
            self.assertNotIn("I said the file", excerpts)
            flag = next(f for f in result["flags"] if f["name"] == "intervention-must-automate")
            self.assertEqual(flag["value"], "no")
        finally:
            os.unlink(path)


class TestOmpFrustrationAndOut(unittest.TestCase):
    """OMP mode gained --out and the frustration detector together; the
    interruption shapes (customType=interrupted-thinking, 'Skipped due to
    queued user message' tool results) were verified against a real session
    (7 + 14 markers) before writing this."""

    def test_omp_counts_interruptions_and_writes_out_report(self):
        lines = [
            {"type": "message", "timestamp": "2026-08-18T02:30:00Z",
             "message": {"role": "user", "content": [
                 {"type": "text", "text": "WHY IS MY VOICE ROBOTIC? FIX IT RIGHT NOW PLEASE"}]}},
            {"type": "custom", "customType": "interrupted-thinking"},
            {"type": "message", "message": {"role": "toolResult", "toolCallId": "c1", "isError": True,
             "content": [{"type": "text", "text": "Skipped due to queued user message."}]}},
            omp_assistant_line([{"type": "text", "text": "ok"}],
                               usage={"input": 1, "output": 2, "cacheRead": 3, "cacheWrite": 4,
                                      "totalTokens": 10, "cost": {"total": 0.01}}),
        ]
        path = write_jsonl(lines)
        out = tempfile.NamedTemporaryFile(suffix=".json", delete=False).name
        try:
            with redirect_stdout(io.StringIO()):
                result = token_audit.audit_omp(path, out_path=out)
            self.assertEqual(result["frustration"]["n_user_messages"], 1)
            self.assertEqual(result["frustration"]["count"], 1)
            self.assertEqual(result["frustration"]["interruptions"], 2)
            with open(out) as f:
                report = json.load(f)
            self.assertEqual(report["totals"]["total"], 10)
            self.assertEqual(report["totals"]["n_errors"], 1)
            flag = next(f_ for f_ in report["flags"] if f_["name"] == "frustration-signals")
            self.assertEqual(flag["value"], "yes")
        finally:
            os.unlink(path)
            os.unlink(out)


class TestPathAliasNormalization(unittest.TestCase):
    """Ported from PR #1: some tool variants pass `path` instead of
    `file_path`; both must land in the same dedup/streak buckets, without
    conflating genuinely different files."""

    def test_path_alias_read_twice_is_thrash(self):
        u = {"input_tokens": 1, "output_tokens": 1}
        lines = [
            claude_assistant_line("m1", "u1", [
                {"type": "tool_use", "id": "t1", "name": "Read", "input": {"path": "/a.py"}}], u),
            claude_assistant_line("m2", "u2", [
                {"type": "tool_use", "id": "t2", "name": "Read", "input": {"path": "/a.py"}}], u),
        ]
        path = write_jsonl(lines)
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                token_audit.audit_claude(path)
            out = buf.getvalue()
            self.assertIn("  /a.py offset/limit=(None, None)", out)
            self.assertIn("redundant re-reads (identical window): 1", out)
        finally:
            os.unlink(path)

    def test_path_alias_keeps_different_files_distinct(self):
        u = {"input_tokens": 1, "output_tokens": 1}
        lines = [
            claude_assistant_line("m1", "u1", [
                {"type": "tool_use", "id": "t1", "name": "Read", "input": {"path": "/a.py"}}], u),
            claude_assistant_line("m2", "u2", [
                {"type": "tool_use", "id": "t2", "name": "Read", "input": {"path": "/b.py"}}], u),
        ]
        path = write_jsonl(lines)
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                token_audit.audit_claude(path)
            self.assertIn("redundant re-reads (identical window): 0", buf.getvalue())
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
