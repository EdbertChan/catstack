#!/usr/bin/env python3
"""Tests for verify_stack.py --queue-feedback against real Mergify comments.

fixtures/mergify_queue_comments_2026-10-12.json holds every comment Mergify
posted on six real PRs, as `gh api issues/<n>/comments` returned them:
"1309" was dequeued for merge conflicts after a timed-out batch; "1333" and
"1332" were dequeued by timeouts and then requeued; "1354" is queued and
preparing checks; Invoker "15193" was dequeued because the PR Body check
failed; Invoker "15249" is running queue checks.

"derived-waiting-from-catstack#1354" is the real "checking" comment from #1354
with its payload state changed to "waiting", the value Mergify reported
("Waiting for queue conditions") on #1354 after a head update. Mergify edits
that comment in place, so the original could not be saved.
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

FIXTURE = os.path.join(HERE, "fixtures", "mergify_queue_comments_2026-10-12.json")
SCRIPT = os.path.join(os.path.dirname(HERE), "scripts", "verify_stack.py")


def load():
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)


def status_comments(rows):
    return [r for r in rows if "# Merge Queue Status" in r["body"]]


class TestQueueFeedback(unittest.TestCase):
    def test_conflict_dequeue_is_rejected_with_a_rebase_action(self):
        fb = vs.queue_feedback(load()["catstack#1309"])
        self.assertEqual(fb["state"], "rejected")
        self.assertEqual(fb["kind"], "conflict")
        self.assertIn("merge conflicts", fb["reason"])
        self.assertIn("rebase", fb["action"].lower())

    def test_timeout_dequeue_is_rejected_as_timeout(self):
        only_timeout = [status_comments(load()["catstack#1333"])[0]]
        fb = vs.queue_feedback(only_timeout)
        self.assertEqual(fb["state"], "rejected")
        self.assertEqual(fb["kind"], "timeout")
        self.assertIn("checks timeout", fb["reason"])
        self.assertIn("checks_timeout", fb["action"])

    def test_batch_ahead_failure_is_a_recheck_not_a_rejection(self):
        rows = [r for r in status_comments(load()["catstack#1332"])
                if "which was ahead in the queue failed" in r["body"]]
        self.assertTrue(rows, "fixture lost the batch-ahead comment")
        fb = vs.queue_feedback(rows[:1])
        self.assertEqual(fb["state"], "in-queue")
        self.assertEqual(fb["kind"], "ahead-failed")

    def test_timeout_names_the_check_that_was_still_running(self):
        only_timeout = [status_comments(load()["catstack#1333"])[0]]
        self.assertEqual(vs.queue_feedback(only_timeout)["still_running"], ["test"])

    def test_failed_check_names_the_check(self):
        fb = vs.queue_feedback(load()["Invoker#15193"])
        self.assertEqual(fb["state"], "rejected")
        self.assertEqual(fb["kind"], "checks-failed")
        self.assertIn("PR Body", fb["failing_checks"])

    def test_requeued_pr_reports_the_latest_comment_not_the_old_dequeue(self):
        rows = load()["catstack#1333"]
        self.assertTrue(any('"state": "dequeued"' in r["body"] for r in rows))
        fb = vs.queue_feedback(rows)
        self.assertEqual(fb["state"], "in-queue")

    def test_queued_pr_is_in_queue_with_rule(self):
        fb = vs.queue_feedback(load()["catstack#1354"])
        self.assertEqual(fb["state"], "in-queue")
        self.assertEqual(fb["rule"], "admin-bypass")

    def test_waiting_for_conditions_is_waiting_not_unchecked(self):
        fb = vs.queue_feedback(load()["derived-waiting-from-catstack#1354"])
        self.assertEqual(fb["state"], "waiting")
        self.assertIn("conditions", fb["reason"])

    def test_rejection_older_than_the_head_commit_is_waiting(self):
        rows = load()["catstack#1309"]
        stale = vs.queue_feedback(rows, head_at="2026-10-12T19:00:00Z")
        self.assertEqual(stale["state"], "waiting")
        self.assertIn("head", stale["reason"])

    def test_rejection_newer_than_the_head_commit_stays_rejected(self):
        rows = load()["catstack#1309"]
        fb = vs.queue_feedback(rows, head_at="2026-10-12T14:00:00Z")
        self.assertEqual(fb["state"], "rejected")

    def test_no_status_comment_is_unchecked(self):
        fb = vs.queue_feedback([])
        self.assertEqual(fb["state"], "unchecked")
        self.assertIn("no Merge Queue Status comment", fb["reason"])

    def test_unreadable_payload_is_unchecked_not_in_queue(self):
        broken = [{"id": 1, "body": "# Merge Queue Status\n\n- something new Mergify added\n"}]
        fb = vs.queue_feedback(broken)
        self.assertEqual(fb["state"], "unchecked")

    def test_cli_exit_codes_replay_json(self):
        data = load()
        path = os.path.join(os.environ.get("TMPDIR", "/tmp"), "queue_feedback_cli_test.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"1309": data["catstack#1309"], "1354": data["catstack#1354"]}, fh)
        try:
            rejected = subprocess.run([sys.executable, SCRIPT, "--queue-feedback", "--feedback-json", path, "1309"],
                                      capture_output=True, text=True)
            ok = subprocess.run([sys.executable, SCRIPT, "--queue-feedback", "--feedback-json", path, "1354"],
                                capture_output=True, text=True)
        finally:
            os.unlink(path)
        self.assertEqual(rejected.returncode, 1, rejected.stdout + rejected.stderr)
        self.assertIn("rejected", rejected.stdout)
        self.assertIn("#1309", rejected.stdout)
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        self.assertIn("in-queue", ok.stdout)


if __name__ == "__main__":
    unittest.main()
