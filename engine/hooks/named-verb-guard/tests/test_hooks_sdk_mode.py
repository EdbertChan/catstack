from __future__ import annotations

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOK_DIR)

import claude_stop_check  # noqa: E402
import detect  # noqa: E402


PAYLOAD = {
    "hook_event_name": "Stop",
    "session_id": "named-verb-sdk",
    "transcript_path": "/nonexistent/session.jsonl",
    "last_assistant_message": "Tests pass.",
}


class SdkEntryTest(unittest.TestCase):
    def test_entry_runs_through_shared_runtime_and_hands_off_to_the_judge(self) -> None:
        out, err = io.StringIO(), io.StringIO()
        with patch.object(detect, "try_enqueue_judge") as enqueue, \
                patch.object(sys, "stdin", io.StringIO(json.dumps(PAYLOAD))), \
                redirect_stdout(out), redirect_stderr(err):
            with self.assertRaises(SystemExit) as caught:
                claude_stop_check.main()
        self.assertEqual(0, caught.exception.code)
        enqueue.assert_called_once()
        self.assertEqual("", out.getvalue())

    def test_detect_never_waits_for_a_verdict(self) -> None:
        with patch.object(detect, "try_enqueue_judge"):
            self.assertEqual([], detect.detect(dict(PAYLOAD)))


if __name__ == "__main__":
    unittest.main()
