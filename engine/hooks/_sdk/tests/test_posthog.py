from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SDK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SDK_DIR))

import posthog


class PosthogPublishTest(unittest.TestCase):
    def test_no_api_key_is_noop(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            env = {k: v for k, v in os.environ.items() if not k.startswith("CATSTACK_POSTHOG_")}
            env["HOME"] = home
            env.pop("CATSTACK_ENV_FILE", None)
            self._assert_no_publish(env)

    def _assert_no_publish(self, env: dict[str, str]) -> None:
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

    def test_api_key_from_catstack_env_file_starts_thread(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            Path(home, ".catstack.env").write_text(
                "CATSTACK_POSTHOG_API_KEY=phc_from_file\nCATSTACK_POSTHOG_HOST=https://example.test\n",
                encoding="utf-8",
            )
            env = {k: v for k, v in os.environ.items() if not k.startswith("CATSTACK_POSTHOG_")}
            env["HOME"] = home
            env.pop("CATSTACK_ENV_FILE", None)
            with mock.patch.dict(os.environ, env, clear=True), mock.patch("posthog.threading.Thread") as thread_cls:
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
                kwargs = thread_cls.call_args.kwargs
                self.assertEqual(kwargs["args"][0], "https://example.test")
                self.assertEqual(kwargs["args"][1][0]["api_key"], "phc_from_file")
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
                "catstack_sha": "a" * 40,
                "invoker_version": "0.2.1",
                "invoker_sha": "",
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
        self.assertEqual("a" * 40, props["catstack_sha"])
        self.assertEqual("0.2.1", props["invoker_version"])
        self.assertEqual("", props["invoker_sha"])
        self.assertEqual("diu-stop", props["hook"])


if __name__ == "__main__":
    unittest.main()
