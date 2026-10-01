from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

SDK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SDK_DIR))

import posthog


class PosthogPublishTest(unittest.TestCase):
    def test_no_api_key_is_noop(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "CATSTACK_POSTHOG_API_KEY"}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch("posthog.threading.Thread") as thread_cls:
            posthog.publish_rows(
                [
                    {
                        "hook": "wait-needs-wakeup",
                        "harness": "claude",
                        "rule_id": "x",
                        "action": "stopped",
                        "mode": "stop",
                        "machine": "do1",
                        "session_id": "s1",
                        "model": "claude-sonnet-5",
                        "duration_ms": 3,
                        "ts": "2026-10-01T00:00:00+00:00",
                    }
                ]
            )
            thread_cls.assert_not_called()

    def test_api_key_starts_background_thread(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"CATSTACK_POSTHOG_API_KEY": "phc_test", "CATSTACK_POSTHOG_HOST": "https://example.test"},
            clear=False,
        ), mock.patch("posthog.threading.Thread") as thread_cls:
            thread_cls.return_value = mock.Mock()
            posthog.publish_rows(
                [
                    {
                        "hook": "wait-needs-wakeup",
                        "harness": "claude",
                        "rule_id": "x",
                        "action": "stopped",
                        "mode": "stop",
                        "machine": "do1",
                        "session_id": "s1",
                        "model": "claude-sonnet-5",
                        "duration_ms": 3,
                        "ts": "2026-10-01T00:00:00+00:00",
                    }
                ]
            )
            thread_cls.assert_called_once()
            thread_cls.return_value.start.assert_called_once()

    def test_capture_body_omits_subject_and_transcript(self) -> None:
        body = posthog._capture_body(
            "phc_test",
            {
                "hook": "diu-stop",
                "harness": "claude",
                "rule_id": "diu-stop.word-limit",
                "action": "stopped",
                "mode": "stop",
                "machine": "do1",
                "session_id": "s1",
                "model": "claude-opus-5",
                "duration_ms": 9,
                "ts": "2026-10-01T00:00:00+00:00",
                "subject_hash": "should-not-appear",
                "command": "should-not-appear",
            },
        )
        props = body["properties"]
        self.assertEqual(posthog.EVENT_NAME, body["event"])
        self.assertNotIn("subject_hash", props)
        self.assertNotIn("command", props)
        self.assertEqual("claude-opus-5", props["model"])
        self.assertEqual("diu-stop", props["hook"])


if __name__ == "__main__":
    unittest.main()
