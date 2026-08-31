#!/usr/bin/env python3
"""Positive/negative fixtures for structural role-user provenance."""
from __future__ import annotations

import os
import sys
import unittest

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS_DIR)

import transcript_provenance as provenance  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "provenance")


class TestTranscriptProvenance(unittest.TestCase):
    def test_positive_direct_human_carries_typed_identity_for_each_harness(self):
        for harness in ("claude", "codex", "cursor"):
            with self.subTest(harness=harness):
                path = os.path.join(FIXTURES, "direct", f"{harness}.jsonl")
                rows = provenance.direct_human_utterances(path, harness)
                self.assertEqual(len(rows), 3)
                self.assertIsInstance(rows[0], provenance.HumanUtterance)
                self.assertEqual(rows[0].harness, harness)
                self.assertEqual(rows[0].provenance, "direct_human")
                self.assertTrue(rows[0].lineage_id)
                self.assertTrue(rows[0].session_id)
                self.assertTrue(rows[0].timestamp)
                self.assertEqual(rows[0].text, "make a PR")

    def test_negative_injections_are_typed_but_cannot_trigger_automation(self):
        expected = {
            "claude": {"hook", "system"},
            "codex": {"system"},
            "cursor": {"system"},
        }
        for harness, provenances in expected.items():
            with self.subTest(harness=harness):
                path = os.path.join(FIXTURES, "injected", f"{harness}.jsonl")
                rows = provenance.extract_utterances(path, harness)
                self.assertEqual({row.provenance for row in rows}, provenances)
                self.assertFalse(any(row.can_trigger_intervention for row in rows))
                self.assertEqual(provenance.direct_human_utterances(path, harness), [])

    def test_unknown_user_shaped_events_fail_closed(self):
        for harness in ("claude", "codex", "cursor"):
            with self.subTest(harness=harness):
                path = os.path.join(FIXTURES, "unknown", f"{harness}.jsonl")
                rows = provenance.extract_utterances(path, harness)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].provenance, "unknown")
                self.assertFalse(rows[0].can_trigger_intervention)
                self.assertEqual(provenance.direct_human_utterances(path, harness), [])

    def test_negative_subagent_copies_share_lineage_but_are_not_direct_human(self):
        cases = {
            "claude": ("claude-root.jsonl", "agent-claude.jsonl"),
            "codex": ("codex-root.jsonl", "agent-codex.jsonl"),
            "cursor": (
                os.path.join("cursor-root", "cursor-root.jsonl"),
                os.path.join("cursor-root", "subagents", "agent-cursor.jsonl"),
            ),
        }
        for harness, (main_name, child_name) in cases.items():
            with self.subTest(harness=harness):
                main_path = os.path.join(FIXTURES, "lineage", main_name)
                child_path = (
                    os.path.join(FIXTURES, "lineage", child_name)
                    if harness == "cursor"
                    else os.path.join(FIXTURES, "lineage", "subagents", child_name)
                )
                main = provenance.extract_utterances(main_path, harness)
                child = provenance.extract_utterances(child_path, harness)
                self.assertEqual(main[0].lineage_id, child[0].lineage_id)
                self.assertNotEqual(main[0].session_id, child[0].session_id)
                self.assertEqual(main[0].provenance, "direct_human")
                self.assertEqual(child[0].provenance, "subagent")
                self.assertFalse(child[0].can_trigger_intervention)


if __name__ == "__main__":
    unittest.main()
