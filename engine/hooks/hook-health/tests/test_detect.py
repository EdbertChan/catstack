from __future__ import annotations

import os
import sys
import unittest

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOK_DIR)

import detect


class DetectNotice(unittest.TestCase):
    def row(self, outcome: str, hook: str = "demo", script: str = "x.py", harness: str = "claude") -> dict:
        return {
            "harness": harness,
            "hook": hook,
            "script": script,
            "outcome": outcome,
            "exit_code": 1,
            "stderr_tail": "boom\nmore",
        }

    def test_fires_on_crashed_row_names_hook(self) -> None:
        text = detect.notice([self.row("crashed")], "claude")
        self.assertIsNotNone(text)
        self.assertIn("1 hook run(s) failed", text)
        self.assertIn("demo/x.py crashed (exit 1): boom", text)

    def test_negative_spoke_silent_blocked_rows_return_none(self) -> None:
        rows = [self.row("spoke"), self.row("silent"), self.row("blocked")]
        self.assertIsNone(detect.notice(rows, "claude"))

    def test_hook_health_own_crash_is_ignored(self) -> None:
        self.assertIsNone(detect.notice([self.row("crashed", hook="hook-health")], "claude"))

    def test_over_five_truncation_reports_more(self) -> None:
        rows = [self.row("crashed", hook=f"h{i}") for i in range(7)]
        text = detect.notice(rows, "claude")
        self.assertIsNotNone(text)
        self.assertIn("and 2 more", text)
        self.assertNotIn("h6/x.py", text)

    def test_unreadable_notice_names_unchecked(self) -> None:
        text = detect.unreadable_notice("/tmp/runs.jsonl", "is a directory")
        self.assertIn("could not read the hook metrics log /tmp/runs.jsonl", text)
        self.assertIn("unchecked this turn", text)


if __name__ == "__main__":
    unittest.main()
