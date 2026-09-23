#!/usr/bin/env python3
"""Tests for claimed-search-not-run.

The `grep_only` fixture is the real case, from an Invoker CI-repair session
(bcb34ef9) that closed with:

    Class-search (`git log --all --grep`/`-S`, `gh pr list`) turned up no
    prior fix of this class needing generalization.

Across its 24 Bash calls there is no `git log -S`. The commit-message grep ran;
the code-history search it cited beside it never did, and the conclusion drawn
from the pair was reported as settled.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK_DIR = os.path.dirname(HERE)
sys.path.insert(0, HOOK_DIR)
import detect  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(HOOK_DIR), "_flags"))
import flags  # noqa: E402

_ENFORCEMENT = None


def setUpModule() -> None:
    global _ENFORCEMENT
    _ENFORCEMENT = patch.dict(os.environ, {flags.REFLECT_ENFORCEMENT: "1"})
    _ENFORCEMENT.start()


def tearDownModule() -> None:
    _ENFORCEMENT.stop()


FIXTURES = os.path.join(HERE, "fixtures")
GREP_ONLY = os.path.join(FIXTURES, "grep_only.jsonl")
CODE_HISTORY = os.path.join(FIXTURES, "code_history.jsonl")

REAL_CLAIM = (
    "Class-search (`git log --all --grep`/`-S`, `gh pr list`) turned up no prior "
    "fix of this class needing generalization."
)


def decide(message: str, transcript: str = GREP_ONLY) -> str | None:
    return detect.decide({"last_assistant_message": message, "transcript_path": transcript})


class ClaimedSearchNotRun(unittest.TestCase):
    def test_fires_when_dash_s_is_cited_beside_a_grep_that_did_run(self):
        out = decide(REAL_CLAIM)
        self.assertIsNotNone(out)
        self.assertIn("`git log -S`", out)
        self.assertIn("claimed-search-not-run", out)

    def test_names_the_search_that_did_run_so_the_delta_is_readable(self):
        out = decide(REAL_CLAIM)
        self.assertIn("It did run `git log --grep`", out)

    def test_fires_on_a_plainly_worded_citation(self):
        out = decide("I ran `git blame --follow` on the changed lines and found nothing.")
        self.assertIsNotNone(out)

    def test_silent_when_the_cited_search_actually_ran(self):
        self.assertIsNone(decide(REAL_CLAIM, transcript=CODE_HISTORY))

    def test_silent_when_the_command_is_proposed_not_reported(self):
        self.assertIsNone(decide("Next time we should run `git log -S <token>` to confirm."))
        self.assertIsNone(decide("The fix is to run `git log -S foo` before finalizing."))

    def test_silent_when_no_search_is_cited(self):
        self.assertIsNone(decide("Fixed and proven locally. `pnpm test` passes."))

    def test_silent_when_the_citation_is_not_backticked(self):
        self.assertIsNone(decide("Class-search with git log -S turned up nothing."))

    def test_does_not_read_gh_search_flag_as_git_log_dash_s(self):
        self.assertIsNone(decide("I ran `gh pr list --search foo` and it returned nothing."))

    def test_unreadable_transcript_fails_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "nope.jsonl")
            self.assertIsNone(decide(REAL_CLAIM, transcript=missing))
        self.assertIsNone(detect.decide({"last_assistant_message": REAL_CLAIM}))

    def test_enforcement_flag_off_is_silent(self):
        with patch.dict(os.environ, {flags.REFLECT_ENFORCEMENT: ""}):
            self.assertIsNone(decide(REAL_CLAIM))

    def test_stop_hook_active_is_silent(self):
        self.assertIsNone(detect.decide({
            "last_assistant_message": REAL_CLAIM,
            "transcript_path": GREP_ONLY,
            "stop_hook_active": True,
        }))


class StopCheckEndToEnd(unittest.TestCase):
    def _run(self, payload: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, os.path.join(HOOK_DIR, "claude_stop_check.py")],
            input=payload, capture_output=True, text=True,
            env={**os.environ, flags.REFLECT_ENFORCEMENT: "1"},
        )

    def test_writes_to_stderr_and_exits_zero(self):
        import json
        done = self._run(json.dumps(
            {"last_assistant_message": REAL_CLAIM, "transcript_path": GREP_ONLY}))
        self.assertEqual(done.returncode, 0)
        self.assertIn("claimed-search-not-run", done.stderr)

    def test_malformed_payload_prints_nothing(self):
        done = self._run("not json")
        self.assertEqual(done.returncode, 0)
        self.assertEqual(done.stderr, "")


if __name__ == "__main__":
    unittest.main()
