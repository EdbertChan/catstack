#!/usr/bin/env python3
"""Tests for session_mine.py — no real home-directory transcript scans."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS_DIR)

import session_mine  # noqa: E402


def _claude_jsonl(path: str, texts: list[str]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for text in texts:
            handle.write(
                json.dumps(
                    {
                        "type": "user",
                        "message": {"role": "user", "content": text},
                    }
                )
                + "\n"
            )


class TestRunMine(unittest.TestCase):
    def test_writes_queue_with_ready_when_yes_and_no_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = os.path.join(tmp, "a.jsonl")
            b = os.path.join(tmp, "b.jsonl")
            c = os.path.join(tmp, "c.jsonl")
            _claude_jsonl(a, ["make a PR"])
            _claude_jsonl(b, ["make a PR"])
            _claude_jsonl(c, ["don't make a PR yet", "make a PR"])
            state = os.path.join(tmp, "state")
            with patch.object(
                session_mine, "discover_intervention_paths", return_value=[a, b, c]
            ):
                with patch.object(session_mine, "open_pr_hashes_for_cluster", return_value=[]):
                    queue = session_mine.run_mine(
                        hours=24,
                        state_dir=state,
                        min_sessions=3,
                        min_utterances=5,
                        events_path=None,
                    )
            self.assertTrue(os.path.isfile(os.path.join(state, "queue.json")))
            ready = queue.get("pending_headless") or []
            self.assertEqual(len(ready), 1)
            self.assertEqual(ready[0]["cluster_key"], "make_pr")
            self.assertTrue(ready[0].get("ready_for_headless"))

    def test_cooldown_blocks_redispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = os.path.join(tmp, "a.jsonl")
            b = os.path.join(tmp, "b.jsonl")
            c = os.path.join(tmp, "c.jsonl")
            _claude_jsonl(a, ["make a PR"])
            _claude_jsonl(b, ["make a PR"])
            _claude_jsonl(c, ["don't open a PR", "make a PR"])
            state = os.path.join(tmp, "state")
            with patch.object(
                session_mine, "discover_intervention_paths", return_value=[a, b, c]
            ):
                with patch.object(session_mine, "open_pr_hashes_for_cluster", return_value=[]):
                    q1 = session_mine.run_mine(
                        hours=24,
                        state_dir=state,
                        min_sessions=3,
                        min_utterances=3,
                        events_path=None,
                    )
                    h = q1["pending_headless"][0]["hash"]
                    session_mine.mark_headless_dispatched(state, h)
                    q2 = session_mine.run_mine(
                        hours=24,
                        state_dir=state,
                        min_sessions=3,
                        min_utterances=3,
                        events_path=None,
                    )
            self.assertEqual(q2.get("pending_headless"), [])
            blocked = [b for b in q2.get("blocked") or [] if b.get("blocked_reason") == "cooldown"]
            self.assertTrue(blocked)


if __name__ == "__main__":
    unittest.main()
