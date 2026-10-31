#!/usr/bin/env python3
"""Unit tests for subagent_cost.py.

Run: python3 -m unittest discover -s skills/reflect/scripts/tests -v
(stdlib unittest only - no pytest in this environment)

Fixtures are small synthetic JSONL built inline, not real user transcripts.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS_DIR)

import subagent_cost  # noqa: E402


def claude_assistant_line(mid, uuid, content_blocks, usage, model="claude-sonnet-5", timestamp=None):
    d = {
        "type": "assistant",
        "uuid": uuid,
        "message": {"id": mid, "model": model, "usage": usage, "content": content_blocks},
    }
    if timestamp:
        d["timestamp"] = timestamp
    return d


def write_agent_transcript(subagents_dir, agent_id, lines, description=None):
    path = os.path.join(subagents_dir, f"agent-{agent_id}.jsonl")
    with open(path, "w") as f:
        for d in lines:
            f.write(json.dumps(d) + "\n")
    if description is not None:
        meta_path = os.path.join(subagents_dir, f"agent-{agent_id}.meta.json")
        with open(meta_path, "w") as f:
            json.dump({"description": description}, f)
    return path


class TestResolveSubagentsDir(unittest.TestCase):
    def test_accepts_session_jsonl_path(self):
        result = subagent_cost.resolve_subagents_dir("/x/y/session-abc.jsonl")
        self.assertEqual(result, "/x/y/session-abc/subagents")

    def test_accepts_session_dir_directly(self):
        result = subagent_cost.resolve_subagents_dir("/x/y/session-abc")
        self.assertEqual(result, "/x/y/session-abc/subagents")


class TestSumSubagentCost(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.session_dir = os.path.join(self.root, "session-abc")
        self.subagents_dir = os.path.join(self.session_dir, "subagents")
        os.makedirs(self.subagents_dir)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_missing_subagents_dir_returns_none(self):
        empty_session_dir = os.path.join(self.root, "no-subagents-here")
        os.makedirs(empty_session_dir)
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = subagent_cost.sum_subagent_cost(empty_session_dir)
        self.assertIsNone(result)
        self.assertIn("No subagents/ directory found", buf.getvalue())

    def test_empty_subagents_dir_returns_none(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = subagent_cost.sum_subagent_cost(self.session_dir)
        self.assertIsNone(result)
        self.assertIn("no agent-*.jsonl files", buf.getvalue())

    def test_sums_tokens_across_multiple_agent_transcripts(self):
        usage_a = {"input_tokens": 1, "output_tokens": 100, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        usage_b = {"input_tokens": 1, "output_tokens": 900, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        write_agent_transcript(
            self.subagents_dir, "aaa",
            [claude_assistant_line("m1", "u1", [{"type": "text", "text": "x"}], usage_a)],
            description="Agent A",
        )
        write_agent_transcript(
            self.subagents_dir, "bbb",
            [claude_assistant_line("m2", "u2", [{"type": "text", "text": "y"}], usage_b)],
            description="Agent B",
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = subagent_cost.sum_subagent_cost(self.session_dir)
        self.assertEqual(result, 1002)  # 101 + 901
        out = buf.getvalue()
        self.assertIn("GRAND TOTAL: 1,002 tokens across 2 subagent(s)", out)
        self.assertIn("Agent A", out)
        self.assertIn("Agent B", out)

    def test_dedupes_by_message_id_reusing_audit_claude_logic(self):
        # Same correctness property token_audit.py's own tests guard: three
        # content blocks sharing one message.id must count usage once, not
        # three times. If subagent_cost.py ever stops routing through
        # audit_claude(), this regresses silently.
        usage = {"input_tokens": 5, "output_tokens": 100, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        lines = [
            claude_assistant_line("m1", "u1", [{"type": "thinking", "thinking": "..."}], usage),
            claude_assistant_line("m1", "u2", [{"type": "text", "text": "hi"}], usage),
            claude_assistant_line("m1", "u3", [{"type": "tool_use", "id": "t1", "name": "Read", "input": {}}], usage),
        ]
        write_agent_transcript(self.subagents_dir, "ccc", lines, description="Dedup check")
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = subagent_cost.sum_subagent_cost(self.session_dir)
        self.assertEqual(result, 105)  # 5 + 100, once, not x3

    def test_missing_meta_json_does_not_crash(self):
        usage = {"input_tokens": 1, "output_tokens": 10, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        write_agent_transcript(
            self.subagents_dir, "nodesc",
            [claude_assistant_line("m1", "u1", [{"type": "text", "text": "x"}], usage)],
            description=None,
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = subagent_cost.sum_subagent_cost(self.session_dir)
        self.assertEqual(result, 11)
        self.assertIn("(no meta.json description)", buf.getvalue())

    def test_reproduces_the_bug_this_script_prevents(self):
        """The exact incident this tool exists to stop: a top-level session
        file sharing a UUID-shaped name with this session's own scratch
        directory, but with no real relationship, must never be silently
        summed in. sum_subagent_cost only ever reads <dir>/subagents/*.jsonl
        - a same-named-but-unrelated file sitting elsewhere is invisible to
        it by construction. This test proves that invisibility, not just
        assert it."""
        unrelated_file = os.path.join(self.root, "unrelated-huge-session.jsonl")
        huge_usage = {"input_tokens": 1, "output_tokens": 999_999, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        with open(unrelated_file, "w") as f:
            f.write(json.dumps(claude_assistant_line("m1", "u1", [{"type": "text", "text": "x"}], huge_usage)) + "\n")

        usage = {"input_tokens": 1, "output_tokens": 10, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        write_agent_transcript(
            self.subagents_dir, "real",
            [claude_assistant_line("m1", "u1", [{"type": "text", "text": "x"}], usage)],
            description="Real subagent",
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = subagent_cost.sum_subagent_cost(self.session_dir)
        self.assertEqual(result, 11)  # NOT 1,000,010 - the unrelated file is never touched


class TestReflectPassCost(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.session_dir = os.path.join(self.root, "session-reflect")
        self.subagents_dir = os.path.join(self.session_dir, "subagents")
        os.makedirs(self.subagents_dir)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    @staticmethod
    def usage(output_tokens):
        return {
            "input_tokens": 0,
            "output_tokens": output_tokens,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }

    def write_agent(self, agent_id, description, turn_tokens):
        lines = []
        for index, tokens in enumerate(turn_tokens):
            message_id = f"{agent_id}-m{index}"
            lines.append(claude_assistant_line(
                message_id, f"{message_id}-a", [{"type": "thinking", "thinking": "..."}],
                self.usage(tokens)))
            lines.append(claude_assistant_line(
                message_id, f"{message_id}-b", [{"type": "text", "text": "x"}],
                self.usage(tokens)))
        write_agent_transcript(self.subagents_dir, agent_id, lines, description=description)

    def build_one_pass_of_each_bucket(self):
        self.write_agent("orch", "Reflect: chaos transcript", [1000, 2000])
        self.write_agent("lensa", "Reflect lens: Cost", [100])
        self.write_agent("lensb", "Reflect lens: Judgment", [200, 300])
        self.write_agent("synth", "Reflect step 4 synthesis", [500])
        self.write_agent("applya", "Apply Accepted findings in the reflect worktree", [50, 60, 70])

    def test_buckets_every_reflect_agent_with_tokens_and_turns(self):
        self.build_one_pass_of_each_bucket()
        report = subagent_cost.reflect_pass_cost(self.session_dir)
        self.assertIsNone(report["unchecked"])
        self.assertEqual(report["agent_count"], 5)
        self.assertEqual(report["total_tokens"], 4280)
        self.assertEqual(report["buckets"]["orchestrator"], {"tokens": 3000, "turns": 2})
        self.assertEqual(report["buckets"]["lenses"], {"tokens": 600, "turns": 3})
        self.assertEqual(report["buckets"]["synthesis"], {"tokens": 500, "turns": 1})
        self.assertEqual(report["buckets"]["apply"], {"tokens": 180, "turns": 3})

    def test_prints_the_one_line_pr_body_form(self):
        self.build_one_pass_of_each_bucket()
        buf = io.StringIO()
        with redirect_stdout(buf):
            readable = subagent_cost.print_reflect_pass_cost(self.session_dir)
        self.assertTrue(readable)
        self.assertEqual(
            buf.getvalue().strip(),
            "Reflect pass cost: 5 agents, 4,280 tokens (orchestrator 3,000/2, "
            "lenses 600/3, synthesis 500/1, apply 180/3)",
        )

    def test_turn_count_dedupes_blocks_sharing_one_message_id(self):
        self.write_agent("lensa", "Reflect lens: Cost", [100, 100, 100])
        report = subagent_cost.reflect_pass_cost(self.session_dir)
        self.assertEqual(report["buckets"]["lenses"]["turns"], 3)

    def test_synthesis_accepts_the_shorter_description(self):
        self.write_agent("synth", "Reflect synthesis", [500])
        report = subagent_cost.reflect_pass_cost(self.session_dir)
        self.assertEqual(report["buckets"]["synthesis"]["tokens"], 500)

    def test_bucket_for_each_description_shape(self):
        self.assertEqual(subagent_cost.reflect_bucket_for("Reflect lens: Cost"), "lenses")
        self.assertEqual(subagent_cost.reflect_bucket_for("Reflect step 4 synthesis"), "synthesis")
        self.assertEqual(subagent_cost.reflect_bucket_for("Reflect synthesis"), "synthesis")
        self.assertEqual(subagent_cost.reflect_bucket_for("Reflect steps 1-4"), "orchestrator")
        self.assertEqual(subagent_cost.reflect_bucket_for("Apply the accepted edits"), "apply")
        self.assertEqual(subagent_cost.reflect_bucket_for(None), "apply")

    def test_missing_subagents_dir_is_unchecked_not_zero(self):
        empty_session_dir = os.path.join(self.root, "no-subagents-here")
        os.makedirs(empty_session_dir)
        buf = io.StringIO()
        with redirect_stdout(buf):
            readable = subagent_cost.print_reflect_pass_cost(empty_session_dir)
        self.assertFalse(readable)
        self.assertIn("Reflect pass cost: unchecked", buf.getvalue())
        self.assertIn("no subagents/ directory", buf.getvalue())

    def test_empty_subagents_dir_is_unchecked_not_zero(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            readable = subagent_cost.print_reflect_pass_cost(self.session_dir)
        self.assertFalse(readable)
        self.assertIn("no agent-*.jsonl files", buf.getvalue())

    def test_unreadable_agent_file_is_named_not_silently_dropped(self):
        self.write_agent("lensa", "Reflect lens: Cost", [100])
        os.makedirs(os.path.join(self.subagents_dir, "agent-unreadable.jsonl"))
        report = subagent_cost.reflect_pass_cost(self.session_dir)
        self.assertEqual(report["agent_count"], 1)
        self.assertEqual(len(report["unreadable"]), 1)
        self.assertIn("agent-unreadable.jsonl", report["unreadable"][0])
        line = subagent_cost.format_reflect_pass_cost(report)
        self.assertIn("unchecked: 1 agent file(s)", line)
        self.assertIn("agent-unreadable.jsonl", line)

    def test_empty_agent_transcript_counts_as_zero_tokens_and_zero_turns(self):
        write_agent_transcript(self.subagents_dir, "blank", [], description="Reflect lens: History")
        report = subagent_cost.reflect_pass_cost(self.session_dir)
        self.assertEqual(report["agent_count"], 1)
        self.assertEqual(report["unreadable"], [])
        self.assertEqual(report["buckets"]["lenses"], {"tokens": 0, "turns": 0})


class TestContextCostWithoutAParentTranscript(unittest.TestCase):
    """A session whose own <id>.jsonl is gone but whose subagents/ survive."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.session_dir = os.path.join(self.root, "session-orphan")
        self.subagents_dir = os.path.join(self.session_dir, "subagents")
        os.makedirs(self.subagents_dir)
        usage = {
            "input_tokens": 0,
            "output_tokens": 100,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }
        write_agent_transcript(
            self.subagents_dir, "lensa",
            [claude_assistant_line("m0", "m0-a", [{"type": "text", "text": "x"}], usage)],
            description="Reflect lens: Cost")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_missing_parent_transcript_is_named_not_a_traceback(self):
        report = subagent_cost.analyze_context_cost(self.session_dir)
        self.assertEqual(report["parent_spend"], 0)
        self.assertIn("session-orphan.jsonl", report["parent_spend_unchecked"])
        self.assertEqual(report["child_spend"], 100)
        self.assertEqual(report["child_count"], 1)

    def test_default_report_exits_zero_and_names_the_missing_parent(self):
        completed = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS_DIR, "subagent_cost.py"), self.session_dir],
            capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("GRAND TOTAL: 100 tokens", completed.stdout)
        self.assertIn("parent_spend_unchecked=", completed.stdout)
        self.assertNotIn("Traceback", completed.stderr)

    def test_a_present_parent_transcript_adds_no_unchecked_line(self):
        session_transcript = self.session_dir + ".jsonl"
        with open(session_transcript, "w") as handle:
            handle.write(json.dumps(claude_assistant_line(
                "p0", "p0-a", [{"type": "text", "text": "x"}],
                {"input_tokens": 1, "output_tokens": 2,
                 "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0})) + "\n")
        completed = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS_DIR, "subagent_cost.py"), self.session_dir],
            capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertNotIn("parent_spend_unchecked", completed.stdout)


if __name__ == "__main__":
    unittest.main()
