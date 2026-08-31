#!/usr/bin/env python3
"""Tests for cluster_interventions.py — synthetic fixtures only, no real transcripts."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS_DIR)

import cluster_interventions as ci  # noqa: E402


FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "provenance")


def _write_claude_jsonl(path: str, user_texts: list[str]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for text in user_texts:
            handle.write(
                json.dumps(
                    {
                        "type": "user",
                        "message": {"role": "user", "content": text},
                        "timestamp": "2026-08-24T12:00:00Z",
                    }
                )
                + "\n"
            )


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


if __name__ == "__main__":
    unittest.main()
