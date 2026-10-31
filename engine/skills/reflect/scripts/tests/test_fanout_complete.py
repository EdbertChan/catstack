#!/usr/bin/env python3
"""A reflect fan-out is complete only when every launched lens reported.

The failure this exists to stop: a lens dies, the survivors return findings,
and step 5 applies them as though the pass were whole. Unreturned reviewers are
not reviewers that passed.

The `unchecked` outcome is pinned as a non-pass on purpose. A fan-out whose
expected set nobody recorded cannot be called complete, and a check that could
not run must not read as clean.

The lens turn targets are pinned here too, and matched against the table in
references/lenses.md in both directions, so the measured target a lens prompt
quotes cannot drift away from the target this script records.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
import fanout_complete as fc  # noqa: E402

SCRIPT = os.path.join(SCRIPTS, "fanout_complete.py")
LENSES_MD = os.path.join(os.path.dirname(SCRIPTS), "references", "lenses.md")


def run(*args):
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)


def lens_targets_in_lenses_md():
    """Turn target per lens as the lenses.md table states it, numeric rows only."""
    with open(LENSES_MD, encoding="utf-8") as handle:
        rows = [line for line in handle if line.startswith("| ") and line.count("|") >= 4]
    targets = {}
    for row in rows:
        cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
        if re.fullmatch(r"\d+", cells[1]):
            targets[cells[0]] = int(cells[1])
    return targets


def write_agent_transcript(path, message_ids, trailing_line=None):
    """Write an agent JSONL whose assistant rows repeat each message id twice."""
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"type": "user", "message": {"content": "go"}}) + "\n")
        for message_id in message_ids:
            for _ in range(2):
                handle.write(json.dumps({"type": "assistant", "message": {"id": message_id}}) + "\n")
        handle.write("\n")
        if trailing_line is not None:
            handle.write(trailing_line + "\n")
    return path


class TestVerdict(unittest.TestCase):
    def test_every_lens_returned_is_complete(self):
        self.assertEqual(fc.verdict(["a", "b"], ["b", "a"])[0], fc.COMPLETE)

    def test_a_missing_lens_is_incomplete_and_named(self):
        outcome, missing, _ = fc.verdict(["a", "b", "c"], ["a"])
        self.assertEqual(outcome, fc.INCOMPLETE)
        self.assertEqual(missing, ["b", "c"])

    def test_no_expected_set_is_unchecked_not_complete(self):
        """The whole point: nothing recorded cannot mean nothing missing."""
        self.assertEqual(fc.verdict([], ["a", "b"])[0], fc.UNCHECKED)
        self.assertNotEqual(fc.verdict([], ["a", "b"])[0], fc.COMPLETE)

    def test_a_lens_nobody_expected_does_not_fill_a_gap(self):
        outcome, missing, unexpected = fc.verdict(["a", "b"], ["a", "zzz"])
        self.assertEqual(outcome, fc.INCOMPLETE)
        self.assertEqual(missing, ["b"])
        self.assertEqual(unexpected, ["zzz"])

    def test_duplicate_returns_do_not_count_twice(self):
        self.assertEqual(fc.verdict(["a", "b"], ["a", "a"])[0], fc.INCOMPLETE)


class TestExitCodes(unittest.TestCase):
    """Exit codes are the contract a caller gates on, so they are pinned."""

    def test_complete_exits_zero(self):
        self.assertEqual(run("--expected", "a", "--returned", "a").returncode, 0)

    def test_incomplete_exits_nonzero_and_names_the_lens(self):
        res = run("--expected", "a", "b", "--returned", "a")
        self.assertEqual(res.returncode, 1)
        self.assertIn("b", res.stdout)

    def test_unchecked_exits_nonzero(self):
        """`unchecked` must not be usable as a pass by a caller reading $?."""
        self.assertEqual(run("--returned", "a").returncode, 2)

    def test_json_carries_the_outcome_and_the_missing_lenses(self):
        res = run("--expected", "a", "b", "--returned", "a", "--json")
        payload = json.loads(res.stdout)
        self.assertEqual(payload["outcome"], "incomplete")
        self.assertEqual(payload["missing"], ["b"])


class TestManifest(unittest.TestCase):
    def test_manifest_drives_the_same_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "run.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"expected": ["a", "b"], "returned": ["a"]}, handle)
            res = run("--manifest", path)
            self.assertEqual(res.returncode, 1)
            self.assertIn("b", res.stdout)

    def test_manifest_without_an_expected_list_is_unchecked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "run.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"returned": ["a"]}, handle)
            self.assertEqual(run("--manifest", path).returncode, 2)


class TestLensTurnTargets(unittest.TestCase):
    """The measured target per lens, and the table a lens prompt quotes from."""

    def test_each_lens_target_is_the_measured_number(self):
        self.assertEqual(fc.LENS_TURN_TARGETS, {
            "Judgment": 10, "Tooling": 10, "Cost": 6,
            "History": 12, "Divergent": 8, "Frustration": 8,
        })

    def test_every_launched_lens_has_a_target(self):
        self.assertEqual(sorted(fc.LENS_TURN_TARGETS), sorted(fc.ALL_LENSES))

    def test_output_cap_is_four_hundred_words(self):
        self.assertEqual(fc.LENS_OUTPUT_WORD_CAP, 400)

    def test_targets_table_matches_the_lenses_reference_both_ways(self):
        """A target quoted in a lens prompt must be the one this script records."""
        self.assertEqual(lens_targets_in_lenses_md(), fc.LENS_TURN_TARGETS)

    def test_a_drifted_reference_target_is_detected(self):
        drifted = dict(lens_targets_in_lenses_md())
        drifted["Cost"] = 99
        self.assertNotEqual(drifted, fc.LENS_TURN_TARGETS)

    def test_recording_the_targets_names_every_expected_lens(self):
        line = fc.render_turn_targets(fc.lens_turn_report(fc.ALL_LENSES))
        self.assertIn("400", line)
        for lens, target in fc.LENS_TURN_TARGETS.items():
            self.assertIn(f"{lens} {target}", line)

    def test_an_expected_lens_with_no_measured_target_is_unchecked(self):
        row = fc.lens_turn_report(["Astrology"])[0]
        self.assertEqual(row["status"], fc.UNCHECKED)
        self.assertIn("no measured turn target for Astrology", row["unchecked"])


class TestAssistantTurnCounting(unittest.TestCase):
    """Actual turns come from distinct assistant message ids, nothing else."""

    def test_repeated_message_ids_count_as_one_turn(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_agent_transcript(os.path.join(tmp, "agent-1.jsonl"), ["a", "b", "c"])
            counted = fc.count_assistant_turns(path)
            self.assertEqual(counted["turns"], 3)
            self.assertEqual(counted["unparsed_lines"], [])

    def test_user_rows_are_not_turns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "agent-1.jsonl")
            with open(path, "w", encoding="utf-8") as handle:
                for _ in range(5):
                    handle.write(json.dumps({"type": "user", "message": {"content": "go"}}) + "\n")
            self.assertEqual(fc.count_assistant_turns(path)["turns"], 0)

    def test_an_unreadable_line_is_named_not_skipped(self):
        """A torn line makes the count a floor, so it is reported with its number."""
        with tempfile.TemporaryDirectory() as tmp:
            path = write_agent_transcript(
                os.path.join(tmp, "agent-1.jsonl"), ["a", "b"], trailing_line="{not json",
            )
            counted = fc.count_assistant_turns(path)
            self.assertEqual(counted["turns"], 2)
            self.assertEqual(len(counted["unparsed_lines"]), 1)
            self.assertIn("line 7", counted["unparsed_lines"][0])


class TestTurnTargetAgainstActual(unittest.TestCase):
    """Target versus actual, with an overrun reported and never cut off."""

    def test_a_lens_inside_its_target_is_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_agent_transcript(os.path.join(tmp, "cost.jsonl"), [f"m{n}" for n in range(4)])
            row = fc.lens_turn_report(["Cost"], {"Cost": path})[0]
            self.assertEqual((row["actual"], row["target"], row["status"]), (4, 6, fc.TARGET_MET))

    def test_a_lens_at_its_target_exactly_is_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_agent_transcript(os.path.join(tmp, "cost.jsonl"), [f"m{n}" for n in range(6)])
            self.assertEqual(fc.lens_turn_report(["Cost"], {"Cost": path})[0]["status"], fc.TARGET_MET)

    def test_an_overrun_is_reported_with_both_numbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_agent_transcript(os.path.join(tmp, "tooling.jsonl"), [f"t{n}" for n in range(17)])
            rows = fc.lens_turn_report(["Tooling"], {"Tooling": path})
            self.assertEqual(rows[0]["status"], fc.TARGET_OVER)
            self.assertIn("Tooling 17/10 over", fc.render_turn_targets(rows))

    def test_a_missing_transcript_is_unchecked_not_ok(self):
        rows = fc.lens_turn_report(["Cost"], {"Cost": "/nonexistent/agent-1.jsonl"})
        self.assertEqual(rows[0]["status"], fc.UNCHECKED)
        self.assertIn("unreadable", rows[0]["unchecked"])
        self.assertIn("unchecked", fc.render_turn_targets(rows))

    def test_a_lens_with_no_transcript_in_a_measured_pass_is_unchecked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_agent_transcript(os.path.join(tmp, "cost.jsonl"), ["a"])
            rows = fc.lens_turn_report(["Cost", "History"], {"Cost": path})
            self.assertEqual(rows[1]["status"], fc.UNCHECKED)
            self.assertIn("no agent transcript given for History", rows[1]["unchecked"])

    def test_a_torn_transcript_is_unchecked_not_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_agent_transcript(
                os.path.join(tmp, "cost.jsonl"), ["a", "b"], trailing_line="{not json",
            )
            rows = fc.lens_turn_report(["Cost"], {"Cost": path})
            self.assertEqual(rows[0]["status"], fc.UNCHECKED)
            self.assertIn("is a floor", rows[0]["unchecked"])

    def test_no_expected_set_cannot_be_called_on_target(self):
        line = fc.render_turn_targets(fc.lens_turn_report([]))
        self.assertIn("unchecked", line)

    def test_turn_pairs_must_name_their_lens(self):
        with self.assertRaises(ValueError):
            fc.parse_turn_arguments(["cost.jsonl"])


class TestTargetsOnTheCommandLine(unittest.TestCase):
    """The targets line is a report beside the cost line, never a second gate."""

    def test_targets_flag_prints_the_recorded_line(self):
        res = run("--expected", "Cost", "Judgment", "--returned", "Cost", "Judgment", "--targets")
        self.assertEqual(res.returncode, 0)
        self.assertIn("Cost 6", res.stdout)
        self.assertIn("Judgment 10", res.stdout)

    def test_an_overrun_does_not_change_the_exit_code(self):
        """A lens over target is reported, never cut off and never a failed gate."""
        with tempfile.TemporaryDirectory() as tmp:
            path = write_agent_transcript(os.path.join(tmp, "tooling.jsonl"), [f"t{n}" for n in range(17)])
            res = run("--expected", "Tooling", "--returned", "Tooling", "--turns", f"Tooling={path}")
            self.assertEqual(res.returncode, 0)
            self.assertIn("Tooling 17/10 over", res.stdout)

    def test_a_missing_lens_still_fails_with_targets_asked_for(self):
        res = run("--expected", "Cost", "Judgment", "--returned", "Cost", "--targets")
        self.assertEqual(res.returncode, 1)
        self.assertIn("Judgment", res.stdout)

    def test_json_carries_the_targets_when_asked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_agent_transcript(os.path.join(tmp, "cost.jsonl"), ["a", "b"])
            res = run("--expected", "Cost", "--returned", "Cost", "--turns", f"Cost={path}", "--json")
            rows = json.loads(res.stdout)["turn_targets"]
            self.assertEqual(rows[0]["actual"], 2)
            self.assertEqual(rows[0]["target"], 6)
            self.assertEqual(rows[0]["status"], "ok")

    def test_json_omits_the_targets_when_not_asked(self):
        res = run("--expected", "Cost", "--returned", "Cost", "--json")
        self.assertNotIn("turn_targets", json.loads(res.stdout))


if __name__ == "__main__":
    unittest.main()
