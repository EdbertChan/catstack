#!/usr/bin/env python3
"""Tests for verdict-flip-watch.

The `flip` fixture is the real case: check_skill_test_coverage.py printed ok
with its default scope, that was reported as "fully green", and the same script
failed once it was given the slice refs. Nothing mechanical connected the two
runs, so a stale claim stood.
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
    """Every test below is about what this hook does when it is switched on.

    The hook is off unless CATSTACK_REFLECT_ENFORCEMENT says so, so the suite
    opts in the way a user would. TestEnforcementFlag clears the environment
    again to pin the off path.
    """
    global _ENFORCEMENT
    _ENFORCEMENT = patch.dict(os.environ, {flags.REFLECT_ENFORCEMENT: "1"})
    _ENFORCEMENT.start()


def tearDownModule() -> None:
    _ENFORCEMENT.stop()


FIXTURES = os.path.join(HERE, "fixtures")
CLEAN_REPLY = "Opened the PR; here is the link."


def fixture(name: str) -> str:
    return os.path.join(FIXTURES, f"{name}.jsonl")


def payload(name: str, reply: str = CLEAN_REPLY) -> dict:
    return {"last_assistant_message": reply, "transcript_path": fixture(name)}


class IsolatedState(unittest.TestCase):
    """Each test gets its own state dir so once-per-target does not leak."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._prev = detect.STATE_DIR
        detect.STATE_DIR = self._tmp

    def tearDown(self):
        detect.STATE_DIR = self._prev


class TestFindFlip(IsolatedState):
    def test_fires_when_a_verifier_passed_then_failed(self):
        self.assertEqual(
            detect.find_flip(fixture("flip")),
            "scripts/check_skill_test_coverage.py",
        )

    def test_silent_when_the_same_verifier_stays_green(self):
        self.assertIsNone(detect.find_flip(fixture("stable")))

    def test_silent_on_red_then_green_because_that_is_a_fix(self):
        self.assertIsNone(detect.find_flip(fixture("fixed")))

    def test_silent_when_the_flipping_command_is_not_a_verifier(self):
        """An `ls` that succeeds then fails is not a stale verdict."""
        self.assertIsNone(detect.find_flip(fixture("noise")))

    def test_silent_on_unreadable_transcript(self):
        self.assertIsNone(detect.find_flip("/nonexistent/transcript.jsonl"))


class TestClassify(unittest.TestCase):
    def test_fail_wins_over_pass_in_mixed_output(self):
        mixed = "ok      ecosystem boundaries\nfail  engine/skills/make-pr: no test change"
        self.assertEqual(detect.classify(mixed), "fail")

    def test_plain_ok_is_a_pass(self):
        self.assertEqual(detect.classify("ok      skill test coverage"), "pass")

    def test_unittest_ok_is_a_pass(self):
        self.assertEqual(detect.classify("Ran 14 tests in 0.2s\n\nOK"), "pass")

    def test_traceback_is_a_fail(self):
        self.assertEqual(detect.classify("Traceback (most recent call last):"), "fail")

    def test_unrecognised_output_is_unknown(self):
        self.assertEqual(detect.classify("building..."), "unknown")


class TestNormalizeTarget(unittest.TestCase):
    def test_script_path_is_the_target_regardless_of_flags(self):
        self.assertEqual(
            detect.normalize_target("python3 scripts/check_x.py --base a --head b"),
            "scripts/check_x.py",
        )

    def test_runner_without_a_script_falls_back_to_two_words(self):
        self.assertEqual(detect.normalize_target("npm test --silent"), "npm test")

    def test_non_verifier_command_is_not_tracked(self):
        self.assertIsNone(detect.normalize_target("git status --short"))


class TestDecide(IsolatedState):
    def test_blocks_once_then_stays_silent_for_the_same_target(self):
        first = detect.decide(payload("flip"))
        self.assertIsNotNone(first)
        self.assertIn("check_skill_test_coverage.py", first)
        self.assertIsNone(detect.decide(payload("flip")))

    def test_silent_when_the_reply_already_owns_the_flip(self):
        reply = "Correction: that earlier green was vacuous — the gate never compared the slice."
        self.assertIsNone(detect.decide(payload("flip", reply)))

    def test_silent_when_stop_hook_active(self):
        data = payload("flip")
        data["stop_hook_active"] = True
        self.assertIsNone(detect.decide(data))

    def test_silent_without_a_transcript_path(self):
        self.assertIsNone(detect.decide({"last_assistant_message": CLEAN_REPLY}))


class TestHarnessWrapper(IsolatedState):
    def _run(self, data: dict):
        env = dict(os.environ, VERDICT_FLIP_WATCH_STATE_DIR=detect.STATE_DIR)
        return subprocess.run(
            [sys.executable, os.path.join(HOOK_DIR, "claude_stop_check.py")],
            input=json.dumps(data), capture_output=True, text=True, env=env,
        )

    def test_advisory_exits_zero_and_writes_to_stderr(self):
        res = self._run(payload("flip"))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("verdict-flip-watch", res.stderr)

    def test_clean_transcript_is_quiet(self):
        res = self._run(payload("stable"))
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stderr.strip(), "")

    def test_malformed_stdin_fails_open(self):
        res = subprocess.run(
            [sys.executable, os.path.join(HOOK_DIR, "claude_stop_check.py")],
            input="not json", capture_output=True, text=True,
        )
        self.assertEqual(res.returncode, 0)


class TestEnforcementFlag(IsolatedState):
    """verdict-flip-watch is off unless the user opts in.

    It ends in "the admission is a reflect trigger", so it belongs to the
    reflect/automate-me class and answers to the same single switch.
    """

    def env(self, value=None):
        env = {"HOME": self._tmp}
        if value is not None:
            env[flags.REFLECT_ENFORCEMENT] = value
        return patch.dict(os.environ, env, clear=True)

    def test_unset_flag_says_nothing_about_a_real_flip(self):
        with self.env():
            self.assertIsNone(detect.decide(payload("flip")))

    def test_explicit_off_says_nothing(self):
        for value in ("0", "false", "off", "no"):
            with self.subTest(value=value), self.env(value):
                self.assertIsNone(detect.decide(payload("flip")))

    def test_flag_on_still_notes_the_flip(self):
        with self.env("1"):
            self.assertIsNotNone(detect.decide(payload("flip")))


if __name__ == "__main__":
    unittest.main()
