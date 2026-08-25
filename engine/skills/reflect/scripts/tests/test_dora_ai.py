#!/usr/bin/env python3
"""Tests for dora_ai.py — synthetic event streams only."""
from __future__ import annotations

import os
import sys
import unittest

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS_DIR)

import dora_ai  # noqa: E402


class TestLeadPickup(unittest.TestCase):
    def test_approval_to_first_work(self):
        events = [
            {"kind": "plan_approved", "execution_id": "e1", "ts": "2026-08-24T10:00:00Z"},
            {"kind": "first_mutating_work", "execution_id": "e1", "ts": "2026-08-24T10:05:00Z"},
        ]
        samples = dora_ai.lead_pickup_seconds(events)
        self.assertEqual(samples, [300.0])

    def test_zero_delta_dropped(self):
        events = [
            {"kind": "plan_approved", "execution_id": "e1", "ts": "2026-08-24T10:00:00Z"},
            {"kind": "first_mutating_work", "execution_id": "e1", "ts": "2026-08-24T10:00:00Z"},
        ]
        self.assertEqual(dora_ai.lead_pickup_seconds(events), [])


class TestMttr(unittest.TestCase):
    def test_skill_pr_does_not_end_clock(self):
        events = [
            {"kind": "thrash_signal", "incident_id": "i1", "ts": "2026-08-24T10:00:00Z"},
            {"kind": "skill_pr_opened", "incident_id": "i1", "ts": "2026-08-24T10:10:00Z"},
            {"kind": "recovered_verified", "incident_id": "i1", "ts": "2026-08-24T10:30:00Z"},
        ]
        samples = dora_ai.mttr_seconds(events)
        self.assertEqual(samples, [1800.0])


class TestFailRates(unittest.TestCase):
    def test_rework_no_double_count(self):
        events = [
            {"kind": "execution_started", "execution_id": "a"},
            {"kind": "execution_started", "execution_id": "b"},
            {"kind": "execution_thrashed", "execution_id": "a"},
            {"kind": "execution_discarded", "execution_id": "a"},  # same exec
            {"kind": "execution_rewritten", "execution_id": "b"},
        ]
        out = dora_ai.rework_rate(events)
        self.assertEqual(out["started"], 2)
        self.assertEqual(out["failed"], 2)
        self.assertEqual(out["rate"], 1.0)

    def test_post_merge_fail_rate(self):
        events = [
            {"kind": "pr_merged", "pr_id": "1"},
            {"kind": "pr_merged", "pr_id": "2"},
            {"kind": "pr_reverted", "pr_id": "1"},
        ]
        out = dora_ai.post_merge_fail_rate(events)
        self.assertEqual(out["merged"], 2)
        self.assertEqual(out["failed"], 1)
        self.assertEqual(out["rate"], 0.5)


class TestSummarizeElite(unittest.TestCase):
    def test_elite_when_fast_and_clean(self):
        events = [
            {"kind": "plan_approved", "execution_id": "e1", "ts": "2026-08-24T10:00:00Z"},
            {"kind": "first_mutating_work", "execution_id": "e1", "ts": "2026-08-24T10:02:00Z"},
            {"kind": "pr_merged", "pr_id": "1", "auto": True},
            {"kind": "pr_merged", "pr_id": "2", "auto": True},
            {"kind": "pr_merged", "pr_id": "3"},
            {"kind": "pr_merged", "pr_id": "4"},
            {"kind": "pr_merged", "pr_id": "5"},
            {"kind": "pr_merged", "pr_id": "6"},
            {"kind": "pr_merged", "pr_id": "7"},
            {"kind": "pr_merged", "pr_id": "8"},
            {"kind": "pr_merged", "pr_id": "9"},
            {"kind": "pr_merged", "pr_id": "10"},
            {"kind": "pr_merged", "pr_id": "11"},
            {"kind": "pr_merged", "pr_id": "12"},
            {"kind": "pr_merged", "pr_id": "13"},
            {"kind": "pr_merged", "pr_id": "14"},
            {"kind": "execution_started", "execution_id": "e1"},
            {"kind": "execution_started", "execution_id": "e2"},
            {"kind": "execution_started", "execution_id": "e3"},
            {"kind": "execution_started", "execution_id": "e4"},
            {"kind": "execution_started", "execution_id": "e5"},
            {"kind": "execution_started", "execution_id": "e6"},
            {"kind": "execution_started", "execution_id": "e7"},
            {"kind": "execution_thrashed", "execution_id": "e7"},
        ]
        summary = dora_ai.summarize(events, window_days=7.0)
        self.assertTrue(summary["lead_pickup"]["elite"])
        self.assertTrue(summary["deploy_frequency"]["elite"])  # 14/7 = 2.0
        self.assertTrue(summary["rework_rate"]["elite"])  # 1/7 < 0.15


if __name__ == "__main__":
    unittest.main()
