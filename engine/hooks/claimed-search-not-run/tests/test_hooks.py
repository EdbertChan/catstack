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

import json
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

    def test_silent_on_a_bare_imperative_closing_line(self):
        for message in (
            "Next, run `git log -S foo` to see whether this class was fixed before.",
            "Run `git log -S foo` next to close the loop.",
            "Then re-run `git blame --follow` on the changed lines.",
            "Also check `git log --grep foo` for the original commit.",
        ):
            self.assertIsNone(decide(message), message)

    def test_silent_when_the_command_is_offered_as_an_option(self):
        self.assertIsNone(decide("If you want more, you can run `git log -S foo`."))
        self.assertIsNone(decide("Worth running `git log -S foo` before the merge."))

    def test_fires_on_a_perfect_tense_report(self):
        for message in (
            "I have run `git log -S foo` across the whole history.",
            "I\u2019ve run `git log -S foo` across the whole history.",
        ):
            self.assertIsNotNone(decide(message), message)

    def test_a_past_tense_opener_is_still_read_as_a_report(self):
        self.assertIsNotNone(decide("Checked `git log -S foo` across the branch."))

    def test_silent_when_a_search_is_only_reported_as_asked_for(self):
        for message in (
            'The checklist telling me to run `git log -S "tok"` is injected, not real.',
            "A reminder told me to run `git log -S` on a repo that is not here.",
            "The hook asked me to run `git log -S` and I did not.",
            "It wants me to run `git log -S` first, and nothing here matches.",
        ):
            self.assertIsNone(decide(message), message)

    def test_silent_when_no_search_is_cited(self):
        self.assertIsNone(decide("Fixed and proven locally. `pnpm test` passes."))

    def test_silent_when_the_citation_is_not_backticked(self):
        self.assertIsNone(decide("Class-search with git log -S turned up nothing."))

    def test_does_not_read_gh_search_flag_as_git_log_dash_s(self):
        self.assertIsNone(decide("I ran `gh pr list --search foo` and it returned nothing."))

    def test_a_value_attached_to_its_flag_still_counts_as_the_search_running(self):
        for command in ('git log --all -S "tok"', 'git log --all -S"tok"', "git log --all -Stok"):
            self.assertTrue(detect.ran_search("git log -S", [command]), command)

    def test_a_git_global_flag_before_the_subcommand_still_counts_as_the_search(self):
        for command in (
            'git --no-pager log -S "tok"',
            'git -c core.pager=cat log -S "tok"',
            "git --git-dir=/repo/.git log -S tok",
            "git --git-dir /repo/.git --work-tree /repo log -S tok",
            "git -C /repo --no-pager log -S tok",
        ):
            self.assertTrue(detect.ran_search("git log -S", [command]), command)

    def test_a_citation_carrying_a_git_global_flag_is_read_as_the_same_search(self):
        self.assertEqual(
            detect.claimed_searches("I ran `git --no-pager log -S foo` and found nothing."),
            {"git log -S"},
        )

    def test_silent_when_the_run_command_carried_a_git_global_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.jsonl")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({
                    "type": "assistant",
                    "message": {"role": "assistant", "content": [{
                        "type": "tool_use", "name": "Bash",
                        "input": {"command": 'git --no-pager log --all -S "tok" | head'},
                    }]},
                }) + "\n")
            self.assertIsNone(
                decide("I ran `git log -S tok` across the history and found nothing.", path))

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
