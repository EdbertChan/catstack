#!/usr/bin/env python3
"""A second reflect pass in one session reads only the turns the first pass did not.

Three fixtures, one per outcome: no state file means a full pass; a state file
plus new turns means a delta that names the first uncovered line and hands back
the saved findings path; an unreadable state file means `unchecked`, a full
pass that says why, never a silent skip.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
import reflect_pass_state as pass_state  # noqa: E402

SCRIPT = os.path.join(SCRIPTS, "reflect_pass_state.py")
SKILL_MD = os.path.join(os.path.dirname(SCRIPTS), "SKILL.md")


def run(*args):
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)


def assistant_rows(message_id, blocks=2):
    """Claude's layout: one line per content block, every line carrying the same message id."""
    return [{"type": "assistant", "message": {"id": message_id, "content": [{"type": "text", "text": "ok"}]}}
            for _ in range(blocks)]


def write_transcript(path, turns, user_tail=True):
    """Write a session JSONL with the given turn ids, a user row before each and one after."""
    rows = []
    for message_id in turns:
        rows.append({"type": "user", "message": {"role": "user", "content": f"ask {message_id}"}})
        rows.extend(assistant_rows(message_id))
    if user_tail:
        rows.append({"type": "user", "message": {"role": "user", "content": "thanks"}})
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    return path


class PassStateFixtures(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = self.temporary.name
        self.transcript = os.path.join(self.root, "session-1.jsonl")
        self.findings = os.path.join(self.root, "session-1", "reflect-findings.md")
        os.makedirs(os.path.dirname(self.findings))
        with open(self.findings, "w", encoding="utf-8") as handle:
            handle.write("- Accepted: one finding\n")

    def test_no_state_is_a_full_pass(self):
        write_transcript(self.transcript, ["m1", "m2", "m3"])
        read = run("read", self.transcript)
        self.assertEqual(read.returncode, 0, read.stderr)
        self.assertEqual(read.stdout.strip(), "pass-state: none")
        result = run("delta", self.transcript)
        self.assertEqual(result.returncode, pass_state.DELTA_EXIT[pass_state.FULL], result.stderr)
        self.assertTrue(result.stdout.startswith("full  3 turn(s)"), result.stdout)
        self.assertNotIn("unchecked", result.stdout)

    def test_state_plus_new_turns_is_a_delta_with_saved_findings(self):
        write_transcript(self.transcript, ["m1", "m2", "m3"])
        written = run("write", self.transcript, "--last-turn-index", "3",
                      "--findings", self.findings, "--lenses", "Judgment", "Cost", "Frustration")
        self.assertEqual(written.returncode, 0, written.stderr)
        state_file = os.path.join(self.root, "session-1", "reflect-pass.json")
        self.assertTrue(os.path.isfile(state_file))
        with open(state_file, encoding="utf-8") as handle:
            state = json.load(handle)
        self.assertEqual(sorted(state), sorted(pass_state.STATE_KEYS))
        self.assertEqual(state["last_turn_index"], 3)
        self.assertEqual(state["lenses"], ["Judgment", "Cost", "Frustration"])

        read = run("read", self.transcript)
        self.assertEqual(read.returncode, 0, read.stderr)
        self.assertTrue(read.stdout.startswith("pass-state: {"), read.stdout)
        self.assertEqual(json.loads(read.stdout[len("pass-state: "):])["findings_path"], self.findings)

        write_transcript(self.transcript, ["m1", "m2", "m3", "m4", "m5"])
        result = run("delta", self.transcript, "--json")
        self.assertEqual(result.returncode, pass_state.DELTA_EXIT[pass_state.DELTA], result.stderr)
        detail = json.loads(result.stdout)
        self.assertEqual(detail["outcome"], pass_state.DELTA)
        self.assertEqual(detail["new_turns"], 2)
        self.assertEqual(detail["covered_turns"], 3)
        self.assertEqual(detail["findings_path"], self.findings)
        self.assertEqual(detail["lenses"], ["Judgment", "Cost", "Frustration"])
        with open(self.transcript, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        self.assertEqual(json.loads(lines[detail["first_line"] - 1])["message"]["content"], "ask m4")
        self.assertEqual(json.loads(lines[detail["first_line"] - 2])["message"]["id"], "m3")

    def test_state_with_no_new_turns_is_a_delta_of_zero(self):
        write_transcript(self.transcript, ["m1", "m2"])
        run("write", self.transcript, "--last-turn-index", "2", "--findings", self.findings, "--lenses", "Cost")
        result = run("delta", self.transcript, "--json")
        self.assertEqual(result.returncode, pass_state.DELTA_EXIT[pass_state.DELTA], result.stderr)
        self.assertEqual(json.loads(result.stdout)["new_turns"], 0)

    def test_unreadable_state_is_unchecked_never_a_skip(self):
        write_transcript(self.transcript, ["m1", "m2", "m3"])
        state_file = os.path.join(self.root, "session-1", "reflect-pass.json")
        with open(state_file, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        read = run("read", self.transcript)
        self.assertEqual(read.returncode, pass_state.READ_EXIT[pass_state.UNCHECKED])
        self.assertTrue(read.stdout.startswith("pass-state: unchecked "), read.stdout)
        result = run("delta", self.transcript)
        self.assertEqual(result.returncode, pass_state.DELTA_EXIT[pass_state.UNCHECKED])
        self.assertTrue(result.stdout.startswith("full  unchecked "), result.stdout)
        self.assertNotEqual(result.returncode, pass_state.DELTA_EXIT[pass_state.DELTA])

    def test_state_whose_findings_file_is_gone_is_unchecked(self):
        write_transcript(self.transcript, ["m1", "m2"])
        run("write", self.transcript, "--last-turn-index", "2", "--findings", self.findings, "--lenses", "Cost")
        os.remove(self.findings)
        result = run("delta", self.transcript, "--json")
        self.assertEqual(result.returncode, pass_state.DELTA_EXIT[pass_state.UNCHECKED])
        self.assertIn("saved findings missing", json.loads(result.stdout)["reason"])

    def test_state_covering_more_turns_than_the_transcript_is_unchecked(self):
        write_transcript(self.transcript, ["m1", "m2"])
        run("write", self.transcript, "--last-turn-index", "5", "--findings", self.findings, "--lenses", "Cost")
        result = run("delta", self.transcript, "--json")
        self.assertEqual(result.returncode, pass_state.DELTA_EXIT[pass_state.UNCHECKED])
        self.assertIn("covers 5 turns", json.loads(result.stdout)["reason"])

    def test_turns_count_by_distinct_message_id(self):
        write_transcript(self.transcript, ["m1", "m2", "m3"])
        counted = pass_state.count_turns(self.transcript)
        self.assertEqual(counted["ids"], ["m1", "m2", "m3"])
        with open(self.transcript, encoding="utf-8") as handle:
            self.assertEqual(sum(1 for line in handle if '"assistant"' in line), 6)

    def test_subagent_transcript_resolves_to_the_parent_session_dir(self):
        subagent = os.path.join(self.root, "session-1", "subagents", "agent-9.jsonl")
        self.assertEqual(pass_state.state_path(subagent), os.path.join(self.root, "session-1", "reflect-pass.json"))
        self.assertEqual(pass_state.state_path(self.transcript), os.path.join(self.root, "session-1", "reflect-pass.json"))

    def test_help_exits_zero(self):
        result = run("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("reflect-pass.json", result.stdout)


class SkillProseNamesTheState(unittest.TestCase):
    def setUp(self):
        with open(SKILL_MD, encoding="utf-8") as handle:
            self.text = handle.read()

    def section(self, start_marker, end_marker):
        start = self.text.index(start_marker)
        end = self.text.index(end_marker, start)
        return " ".join(self.text[start:end].split())

    def test_step_one_reads_the_state_and_scopes_lenses_to_the_delta(self):
        step_one = self.section("### 1. Locate the transcript(s)", "### 2.")
        self.assertIn("reflect_pass_state.py read", step_one)
        self.assertIn("reflect_pass_state.py delta", step_one)
        self.assertIn("pass-state: none", step_one)
        self.assertIn("pass-state: unchecked", step_one)

    def test_step_four_writes_the_state_after_synthesis(self):
        step_four = self.section("### 4. Synthesize", "### 5.")
        self.assertIn("reflect_pass_state.py write", step_four)
        self.assertIn("reflect-pass.json", step_four)

    def test_chat_line_names_the_incremental_turn_count(self):
        self.assertIn("(incremental: N new turns)", self.text)


if __name__ == "__main__":
    unittest.main()
