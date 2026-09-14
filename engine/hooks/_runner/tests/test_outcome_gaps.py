from __future__ import annotations

import glob
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS_DIR = os.path.dirname(RUNNER_DIR)
sys.path.insert(0, RUNNER_DIR)
sys.path.insert(0, os.path.join(HOOKS_DIR, "llm-judge"))

import judge  # noqa: E402
import outcome  # noqa: E402
import run  # noqa: E402


class MetricsRecordWhatAHookMeant(unittest.TestCase):
    @unittest.expectedFailure
    def test_cursor_allow_reply_is_silent_not_spoke(self):
        self.assertEqual(outcome.classify(0, b'{"continue": true}\n', b"", False), "silent")

    @unittest.expectedFailure
    def test_metrics_row_names_the_rule_that_fired(self):
        row = run._row(
            "/home/u/.claude/hooks",
            "repeat-error-stop",
            "claude_posttooluse.py",
            json.dumps({"hook_event_name": "PostToolUse", "session_id": "s1"}).encode(),
            "blocked",
            0,
            time.monotonic(),
            b'{"decision":"block"}',
            b"",
        )
        self.assertIn("rule_id", row)


class JudgeVerdictsReachMetrics(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.metrics_dir = os.path.join(self.tmp.name, "metrics")
        env = {
            judge.STATE_ENV: os.path.join(self.tmp.name, "judge"),
            "CATSTACK_HOOK_METRICS_DIR": self.metrics_dir,
        }
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)

    @unittest.expectedFailure
    def test_drained_verdict_leaves_a_metrics_row(self):
        transcript = os.path.join(self.tmp.name, "session.jsonl")
        verdict = {"id": "job-1", "hook": "named-verb-guard", "transcript": transcript, "outcome": "hit", "reason": "all true: missing_proof"}
        judge.write_json_atomic(os.path.join(judge.verdict_dir(transcript), "job-1.json"), verdict)

        self.assertEqual([v["id"] for v in judge.drain(transcript)], ["job-1"])

        rows = []
        for path in glob.glob(os.path.join(self.metrics_dir, "*.jsonl")):
            with open(path, encoding="utf-8") as handle:
                rows.extend(json.loads(line) for line in handle if line.strip())
        self.assertTrue(any(row.get("finding_id") == "job-1" for row in rows), rows)


if __name__ == "__main__":
    unittest.main()
