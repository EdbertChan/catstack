#!/usr/bin/env python3
"""Tests for verify_stack.py --queue-state against real catstack check runs.

fixtures/catstack_queue_state_2026-09-11.json holds `gh api` pull and
check-run payloads captured 2026-09-11. "407" is #407 after `@mergifyio
queue`; "409" is #409 after it merged; "407-labelled-only" is #407's
Mergify check run as read while it carried the queue label but had no
`@mergifyio queue` comment, which is the state that was misreported as queued.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import verify_stack as vs  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "catstack_queue_state_2026-09-11.json")
SCRIPT = os.path.join(os.path.dirname(HERE), "scripts", "verify_stack.py")


def load():
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)


class TestQueueState(unittest.TestCase):
    def test_labelled_but_never_queued_is_not_queued(self):
        entry = load()["407-labelled-only"]
        state, why = vs.queue_state(entry["pr"], entry["check_runs"])
        self.assertEqual(state, "not-queued")
        self.assertIn("Merge queue is ready", why)

    def test_running_merge_queue_checks_is_queued(self):
        entry = load()["407"]
        self.assertEqual(vs.queue_state(entry["pr"], entry["check_runs"])[0], "queued")

    def test_merged_pr_is_merged(self):
        entry = load()["409"]
        self.assertEqual(vs.queue_state(entry["pr"], entry["check_runs"])[0], "merged")

    def test_missing_queue_check_run_is_unchecked(self):
        entry = load()["no-mergify-run"]
        state, why = vs.queue_state(entry["pr"], entry["check_runs"])
        self.assertEqual(state, "unchecked")
        self.assertIn("no Mergify Merge Queue check run", why)

    def test_cli_exit_codes(self):
        def run(*keys):
            return subprocess.run([sys.executable, SCRIPT, "--queue-state", "--queue-json", FIXTURE, *keys],
                                  capture_output=True, text=True)
        ok = run("407", "409")
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        bad = run("409", "407-labelled-only")
        self.assertEqual(bad.returncode, 1, bad.stdout + bad.stderr)
        self.assertIn("not-queued", bad.stdout)
        unknown = run("409", "no-mergify-run")
        self.assertEqual(unknown.returncode, 2, unknown.stdout + unknown.stderr)
        self.assertIn("unchecked", unknown.stdout)


if __name__ == "__main__":
    unittest.main()
