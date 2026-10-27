#!/usr/bin/env python3
"""Tests for cluster_interventions.py — synthetic fixtures only, no real transcripts."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS_DIR)

import cluster_interventions as ci  # noqa: E402


FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "provenance")


NOW = datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)


def _write_claude_jsonl(
    path: str, user_texts: list[str], timestamp: str = "2026-08-24T12:00:00Z"
) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for text in user_texts:
            handle.write(
                json.dumps(
                    {
                        "type": "user",
                        "message": {"role": "user", "content": text},
                        "timestamp": timestamp,
                    }
                )
                + "\n"
            )


def _days_before_now(days: float) -> str:
    return (NOW - timedelta(days=days)).isoformat().replace("+00:00", "Z")


class TestNormalizePhrase(unittest.TestCase):
    def test_make_pr_variants(self):
        self.assertEqual(ci.normalize_phrase("make a PR please"), "make_pr")
        self.assertEqual(ci.normalize_phrase("open the pull request"), "make_pr")
        self.assertEqual(ci.normalize_phrase("draft pr"), "make_pr")

    def test_non_intervention_returns_none(self):
        self.assertIsNone(ci.normalize_phrase("fix the auth bug in login.ts"))


class TestCircumstanceBucket(unittest.TestCase):
    def test_negative_dont_pr_yet(self):
        self.assertEqual(ci.circumstance_bucket("don't make a PR yet"), "no")

    def test_positive_bare_make_pr(self):
        self.assertEqual(ci.circumstance_bucket("make a PR"), "yes")


class TestClusterUtterances(unittest.TestCase):
    def test_positive_direct_human_fixtures_cluster_for_each_harness(self):
        for harness in ("claude", "codex", "cursor"):
            with self.subTest(harness=harness):
                path = os.path.join(FIXTURES, "direct", f"{harness}.jsonl")
                utterances = ci.extract_user_utterances(path, kind=harness)
                clusters = ci.cluster_utterances(
                    utterances, min_sessions=1, min_utterances=1
                )
                self.assertEqual(len(clusters), 1)
                self.assertEqual(clusters[0]["cluster_key"], "make_pr")

    def test_negative_observed_injections_stay_silent_for_each_harness(self):
        for harness in ("claude", "codex", "cursor"):
            with self.subTest(harness=harness):
                path = os.path.join(FIXTURES, "injected", f"{harness}.jsonl")
                utterances = ci.extract_user_utterances(path, kind=harness)
                clusters = ci.cluster_utterances(
                    utterances, min_sessions=1, min_utterances=1
                )
                self.assertEqual(clusters, [])

    def test_negative_subagent_copy_does_not_inflate_lineage(self):
        main = os.path.join(FIXTURES, "lineage", "claude-root.jsonl")
        child = os.path.join(
            FIXTURES, "lineage", "subagents", "agent-claude.jsonl"
        )
        utterances = ci.extract_user_utterances(main, kind="claude")
        utterances += ci.extract_user_utterances(child, kind="claude")
        clusters = ci.cluster_utterances(
            utterances, min_sessions=1, min_utterances=1
        )
        self.assertEqual(clusters[0]["utterance_count"], 1)
        self.assertEqual(clusters[0]["session_count"], 1)

    def test_clusters_across_sessions_and_requires_yes_no_for_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = os.path.join(tmp, "a.jsonl")
            b = os.path.join(tmp, "b.jsonl")
            _write_claude_jsonl(a, ["make a PR", "looks good"])
            _write_claude_jsonl(b, ["don't open a PR yet", "make a PR"])
            utterances = ci.extract_user_utterances(a) + ci.extract_user_utterances(b)
            clusters = ci.cluster_utterances(utterances, min_sessions=2, min_utterances=2)
        self.assertEqual(len(clusters), 1)
        c = clusters[0]
        self.assertEqual(c["cluster_key"], "make_pr")
        self.assertGreaterEqual(c["session_count"], 2)
        self.assertTrue(c["circumstance_complete"])
        self.assertGreaterEqual(c["yes_count"], 1)
        self.assertGreaterEqual(c["no_count"], 1)

    def test_incomplete_without_negative(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = os.path.join(tmp, "a.jsonl")
            _write_claude_jsonl(a, ["make a PR", "make a PR again"])
            utterances = ci.extract_user_utterances(a)
            clusters = ci.cluster_utterances(utterances, min_sessions=1, min_utterances=2)
        self.assertEqual(len(clusters), 1)
        self.assertFalse(clusters[0]["circumstance_complete"])

    def test_skips_system_injected_user_turns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "s.jsonl")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "type": "user",
                            "message": {
                                "content": "<command-message>make a PR</command-message>",
                            },
                        }
                    )
                    + "\n"
                )
            utterances = ci.extract_user_utterances(path)
        self.assertEqual(utterances, [])

    def test_loads_committed_yes_no_fixtures(self):
        fixtures = os.path.join(
            os.path.dirname(__file__), "fixtures", "intervention"
        )
        yes_path = os.path.join(fixtures, "make_pr_yes.jsonl")
        no_path = os.path.join(fixtures, "make_pr_no.jsonl")
        utterances = ci.extract_user_utterances(yes_path) + ci.extract_user_utterances(
            no_path
        )
        clusters = ci.cluster_utterances(utterances, min_sessions=1, min_utterances=1)
        self.assertEqual(len(clusters), 1)
        self.assertTrue(clusters[0]["circumstance_complete"])


class TestRecencyWeight(unittest.TestCase):
    def test_one_half_life_halves_the_weight(self):
        self.assertAlmostEqual(
            ci.recency_weight(_days_before_now(21), NOW, 21.0), 0.5, places=9
        )

    def test_today_weighs_one(self):
        self.assertAlmostEqual(
            ci.recency_weight(_days_before_now(0), NOW, 21.0), 1.0, places=9
        )

    def test_zero_half_life_means_raw_counts(self):
        self.assertEqual(ci.recency_weight(_days_before_now(400), NOW, 0.0), 1.0)

    def test_pinned_session_never_decays(self):
        self.assertEqual(
            ci.recency_weight(_days_before_now(400), NOW, 21.0, pinned=True), 1.0
        )

    def test_undated_utterance_weighs_one(self):
        self.assertEqual(ci.recency_weight(None, NOW, 21.0), 1.0)
        self.assertEqual(ci.recency_weight("not-a-timestamp", NOW, 21.0), 1.0)


class TestLoadPinnedSessions(unittest.TestCase):
    def test_missing_file_pins_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                ci.load_pinned_sessions(os.path.join(tmp, "absent.txt")), set()
            )

    def test_blank_lines_and_comments_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "pinned.txt")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("# the founding session\nabc123def456\n\n  789abc  # keep\n")
            self.assertEqual(
                ci.load_pinned_sessions(path), {"abc123def456", "789abc"}
            )


class TestRecencyRanking(unittest.TestCase):
    """A recent small cluster outranks a stale large one; pinning restores it."""

    def _clusters(self, half_life_days, pinned_sessions=frozenset()):
        with tempfile.TemporaryDirectory() as tmp:
            stale_paths = []
            for index in range(4):
                stale = os.path.join(tmp, f"stale-{index}.jsonl")
                _write_claude_jsonl(stale, ["make a PR"], _days_before_now(180))
                stale_paths.append(stale)
            fresh = os.path.join(tmp, "fresh.jsonl")
            _write_claude_jsonl(fresh, ["/reflect on this"], _days_before_now(1))
            utterances = []
            for path in stale_paths + [fresh]:
                utterances.extend(ci.extract_user_utterances(path))
            self.stale_session_hashes = {
                ci.session_hash(u.harness, u.lineage_id)
                for u in utterances
                if ci.normalize_phrase(u.text) == "make_pr"
            }
            return ci.cluster_utterances(
                utterances,
                min_sessions=1,
                min_utterances=1,
                half_life_days=half_life_days,
                now=NOW,
                pinned_sessions=set(pinned_sessions),
            )

    def test_raw_counts_rank_the_stale_cluster_first(self):
        clusters = self._clusters(0.0)
        self.assertEqual([c["cluster_key"] for c in clusters], ["make_pr", "reflect"])
        self.assertEqual(clusters[0]["utterance_count"], 4)
        self.assertEqual(clusters[0]["weight"], 4.0)

    def test_recency_weight_ranks_the_fresh_cluster_first(self):
        clusters = self._clusters(21.0)
        self.assertEqual([c["cluster_key"] for c in clusters], ["reflect", "make_pr"])
        self.assertLess(clusters[1]["weight"], clusters[0]["weight"])
        self.assertEqual(clusters[1]["utterance_count"], 4)
        self.assertLess(clusters[1]["weight"], 1.0)

    def test_pinning_the_stale_sessions_puts_them_back_on_top(self):
        self._clusters(21.0)
        clusters = self._clusters(21.0, pinned_sessions=self.stale_session_hashes)
        self.assertEqual([c["cluster_key"] for c in clusters], ["make_pr", "reflect"])
        self.assertEqual(clusters[0]["weight"], 4.0)
        self.assertEqual(clusters[0]["pinned_session_count"], 4)

    def test_half_life_is_reported_on_every_cluster(self):
        for cluster in self._clusters(21.0):
            self.assertEqual(cluster["half_life_days"], 21.0)
            self.assertEqual(cluster["undated_count"], 0)


if __name__ == "__main__":
    unittest.main()
