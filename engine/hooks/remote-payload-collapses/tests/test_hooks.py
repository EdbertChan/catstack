#!/usr/bin/env python3
"""Tests for the remote-payload-collapses PreToolUse hook.

Run: python3 -m unittest discover -s engine/hooks/remote-payload-collapses/tests -v

The first positive fixture is the verbatim shape that produced
`set: pipefailechoecho: invalid option name` on a user's terminal. The
silent set is led by the pattern that same session had used successfully
four times before regressing: copy the script, run it by path.
"""
from __future__ import annotations

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(HOOK_DIR, "tests", "fixtures")
sys.path.insert(0, HOOK_DIR)

import claude_pretooluse_check  # noqa: E402
import detect  # noqa: E402


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)


def payload(command):
    return {"tool_name": "Bash", "tool_input": {"command": command}}


class TestBlocksCollapsingPayloads(unittest.TestCase):
    def test_hit_every_fires_fixture(self):
        for case in load("commands_fire.json"):
            with self.subTest(label=case["label"]):
                self.assertNotEqual(detect.collapse_risk(case["command"]), "")

    def test_hit_exit_code_is_2_and_names_the_replacement(self):
        case = load("commands_fire.json")[0]
        err = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO(json.dumps(payload(case["command"])))):
            with redirect_stderr(err):
                try:
                    claude_pretooluse_check.main()
                    code = 0
                except SystemExit as exc:
                    code = exc.code
        self.assertEqual(code, 2)
        self.assertIn("scp", err.getvalue())
        self.assertIn("run it by path", err.getvalue())
        self.assertIn("second time", err.getvalue())

    def test_hit_message_quotes_the_reproduced_error(self):
        message = detect.decide(payload(load("commands_fire.json")[0]["command"]))
        self.assertIn("set: -c: invalid option", message)

    def test_hit_the_only_difference_is_the_login_shell_flag(self):
        without = "ssh host 'sudo -u demo -H bash -lc '\"'\"'set -u\necho one'\"'\"''"
        with_i = "ssh host 'sudo -u demo -H -i bash -lc '\"'\"'set -u\necho one'\"'\"''"
        self.assertEqual(detect.collapse_risk(without), "")
        self.assertNotEqual(detect.collapse_risk(with_i), "")


class TestAllowsEverythingElse(unittest.TestCase):
    def test_no_hit_every_silent_fixture(self):
        for case in load("commands_silent.json"):
            with self.subTest(label=case["label"]):
                self.assertIsNone(detect.decide(payload(case["command"])))

    def test_no_hit_without_a_login_shell(self):
        self.assertEqual(detect.collapse_risk("bash -lc '\necho a\necho b\n'"), "")

    def test_no_hit_on_an_empty_or_missing_command(self):
        self.assertIsNone(detect.decide({"tool_name": "Bash", "tool_input": {}}))
        self.assertIsNone(detect.decide({}))

    def test_fails_open_on_garbage_stdin(self):
        err = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("not json")):
            with redirect_stderr(err):
                claude_pretooluse_check.main()
        self.assertEqual(err.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
