from __future__ import annotations

import os
import sys
import unittest

RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER_DIR)

import outcome


class ClassifyOutcomes(unittest.TestCase):
    def test_timed_out_wins(self):
        self.assertEqual(outcome.classify(2, b'{"decision":"block"}', b"", True), "timed_out")

    def test_exit_two_blocks_before_crash(self):
        self.assertEqual(outcome.classify(2, b"", b"", False), "blocked")

    def test_other_nonzero_exit_crashes(self):
        self.assertEqual(outcome.classify(1, b'{"decision":"block"}', b"", False), "crashed")

    def test_stderr_hook_error_is_caught_error(self):
        self.assertEqual(outcome.classify(0, b"", b"catstack-hook-error x\n", False), "caught_error")

    def test_stderr_hook_error_requires_line_start(self):
        self.assertEqual(outcome.classify(0, b"", b"x catstack-hook-error y\n", False), "silent")

    def test_json_decision_block_blocks(self):
        self.assertEqual(outcome.classify(0, b'{"decision":"block"}', b"", False), "blocked")

    def test_json_continue_false_blocks(self):
        self.assertEqual(outcome.classify(0, b'{"continue":false}', b"", False), "blocked")

    def test_json_permission_decision_deny_blocks(self):
        data = b'{"hookSpecificOutput":{"permissionDecision":"deny"}}'
        self.assertEqual(outcome.classify(0, data, b"", False), "blocked")

    def test_json_permission_deny_blocks(self):
        self.assertEqual(outcome.classify(0, b'{"permission":"deny"}', b"", False), "blocked")

    def test_non_json_stdout_speaks(self):
        self.assertEqual(outcome.classify(0, b"{not json", b"", False), "spoke")

    def test_json_array_stdout_speaks(self):
        self.assertEqual(outcome.classify(0, b"[1]", b"", False), "spoke")

    def test_whitespace_stdout_is_silent(self):
        self.assertEqual(outcome.classify(0, b" \n\t", b"", False), "silent")

    def test_empty_stdout_is_silent(self):
        self.assertEqual(outcome.classify(0, b"", b"", False), "silent")


if __name__ == "__main__":
    unittest.main()
