#!/usr/bin/env python3
"""Tests for the token-burn mining scripts.

Reproduces the real failure shapes found in the 2026-09 fleet audit:
codex exec sessions whose input_tokens already include the cached subset
(double-counting inflated fleet totals by ~19B), claude sessions whose
context grows to ~1M then drops on /clear (the sawtooth that makes turns
x context, not task size, the cost driver), and codex rollout files where
cumulative token_count events must not double-count.

Run: python3 -m unittest discover -s corpus/skills/principle-trace-token-burn-loop/tests -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(SKILL_DIR, "scripts"))

import context_growth  # noqa: E402
import scan_session_tokens  # noqa: E402


def write_jsonl(rows):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    for row in rows:
        tmp.write(json.dumps(row) + "\n")
    tmp.close()
    return tmp.name


def claude_assistant(inp, cache_read, out, ts="2026-09-20T00:00:00Z"):
    return {"type": "assistant", "timestamp": ts, "message": {"role": "assistant",
            "usage": {"input_tokens": inp, "cache_read_input_tokens": cache_read,
                      "output_tokens": out}, "content": []}}


class TestScanSessionTokens(unittest.TestCase):
    def test_codex_input_already_includes_cached(self):
        # Real codex usage: total_tokens = input + output; cached_input is a
        # SUBSET of input. The fleet audit initially added cached on top and
        # inflated gross by ~19B tokens — this is the regression guard.
        path = write_jsonl([{
            "type": "turn.completed",
            "usage": {"input_tokens": 1000, "cached_input_tokens": 900,
                      "output_tokens": 50},
        }])
        try:
            r = scan_session_tokens.scan_file(path)
        finally:
            os.unlink(path)
        self.assertEqual(r["agent"], "codex")
        self.assertEqual(scan_session_tokens.gross(r), 1050)
        self.assertEqual(scan_session_tokens.uncached_equiv(r), 150)

    def test_claude_input_excludes_cache_read(self):
        path = write_jsonl([claude_assistant(100, 5000, 30)])
        try:
            r = scan_session_tokens.scan_file(path)
        finally:
            os.unlink(path)
        self.assertEqual(r["agent"], "claude")
        self.assertEqual(scan_session_tokens.gross(r), 5130)
        self.assertEqual(scan_session_tokens.uncached_equiv(r), 130)

    def test_ignores_cumulative_token_count_events(self):
        # codex rollout token_count rows are cumulative per turn — summing
        # them double-counts. Only token_usage_record rows carry per-turn usage.
        path = write_jsonl([
            {"type": "event_msg", "payload": {"type": "token_count", "info": {
                "total_token_usage": {"input_tokens": 500, "output_tokens": 10}}}},
            {"type": "token_usage_record", "payload": {"usage": {
                "input_tokens": 500, "cached_input_tokens": 400, "output_tokens": 10}}},
        ])
        try:
            r = scan_session_tokens.scan_file(path)
        finally:
            os.unlink(path)
        self.assertEqual(scan_session_tokens.gross(r), 510)

    def test_classifies_babysit_and_judge(self):
        self.assertEqual(
            scan_session_tokens.classify("bash ./loop-driver.sh --pr 1", "/x/s.jsonl"),
            "pr-babysit-loop")
        self.assertEqual(
            scan_session_tokens.classify("{}", "/x/-llm-judge-abc/s.jsonl"),
            "llm-judge-one-shot")


class TestContextGrowth(unittest.TestCase):
    def test_sawtooth_counts_clears(self):
        # The 3B-token session shape: grow to ~1M, /clear to ~250K, regrow.
        rows = []
        for cycle in range(3):
            for ctx in (300000, 600000, 900000):
                rows.append(claude_assistant(ctx // 10, ctx - ctx // 10, 100))
            rows.append(claude_assistant(25000, 225000, 100))
        path = write_jsonl(rows)
        try:
            s = context_growth.summarize(path)
        finally:
            os.unlink(path)
        self.assertEqual(s["turns"], 12)
        self.assertEqual(s["peak_ctx"], 900000)
        self.assertEqual(s["clears"], 3)
        self.assertGreater(s["gross"], 6000000)

    def test_codex_rollout_last_token_usage(self):
        rows = []
        for i, inp in enumerate((10000, 25000, 60000)):
            rows.append({"type": "event_msg", "timestamp": f"2026-09-20T00:0{i}:00Z",
                         "payload": {"type": "token_count", "info": {
                             "last_token_usage": {"input_tokens": inp,
                                                  "cached_input_tokens": inp - 1000,
                                                  "output_tokens": 50},
                             "total_token_usage": {"input_tokens": inp * (i + 1),
                                                   "output_tokens": 50}}}})
        path = write_jsonl(rows)
        try:
            pts = [p for p in context_growth.series(path) if "ctx" in p]
        finally:
            os.unlink(path)
        self.assertEqual([p["ctx"] for p in pts], [10000, 25000, 60000])
        self.assertEqual(pts[0]["uncached"], 1000)

    def test_exec_format_flags_whole_turn_only(self):
        path = write_jsonl([{
            "type": "turn.completed",
            "usage": {"input_tokens": 74383580, "cached_input_tokens": 72279296,
                      "output_tokens": 247893},
        }])
        try:
            s = context_growth.summarize(path)
        finally:
            os.unlink(path)
        self.assertEqual(s["gross"], 74383580)
        self.assertIn("whole-turn", s["note"])


if __name__ == "__main__":
    unittest.main()
