#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import importlib
import io
import json
import os
import stat
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOKS_DIR)

claude_stop_check = importlib.import_module("claude_stop_check")
codex_notify = importlib.import_module("codex_notify")
cursor_session = importlib.import_module("cursor_session")
detect = importlib.import_module("detect")

POSITIVE_ONE = "{{CAT-UNVERIFIED: DO1's repair worker is off or stuck -- cannot verify: can't log in to DO1 to look}}"
POSITIVE_TWO = "{{CAT-UNVERIFIED: the fixed `pnpm` command ran instead of the repo's own setup command -- cannot verify: I did not read Invoker's code}}"


def transcript_line(role: str, text: str) -> str:
    return json.dumps({"type": role, "message": {"role": role, "content": [{"type": "text", "text": text}]}})


class TestUnverifiedTagCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.judge_state = os.path.join(self.tmp.name, "judge")
        self.detector_state = os.path.join(self.tmp.name, "state")
        self.env = patch.dict(os.environ, {
            "CATSTACK_LLM_JUDGE_STATE_DIR": self.judge_state,
            "CATSTACK_UNVERIFIED_TAG_CHECK_STATE_DIR": self.detector_state,
        })
        self.env.start()
        self.enqueued = []
        detect._judge.cache_clear()
        self.judge = detect._judge()
        self.enqueue_patch = patch.object(self.judge, "enqueue", side_effect=self.enqueue)
        self.enqueue_patch.start()

    def tearDown(self):
        self.enqueue_patch.stop()
        detect._judge.cache_clear()
        self.env.stop()
        self.tmp.cleanup()

    def enqueue(self, job: dict) -> str:
        self.enqueued.append(dict(job))
        return job["id"]

    def write_transcript(self, text: str = "", name: str = "session.jsonl") -> str:
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            if text:
                handle.write(transcript_line("assistant", text) + "\n")
        return path

    def check(self, text: str, path: str | None = None) -> list[str]:
        transcript = path or self.write_transcript()
        return detect.check_reply({
            "transcript_path": transcript,
            "last_assistant_message": text,
            "cwd": self.tmp.name,
        })

    def test_hit_one_job_per_tag(self):
        path = self.write_transcript()
        ids = self.check(f"{POSITIVE_ONE}\n\n{POSITIVE_TWO}", path)
        self.assertEqual(ids, [job["id"] for job in self.enqueued])
        self.assertEqual(len(self.enqueued), 2)
        self.assertEqual(set(self.enqueued[0]), {
            "id",
            "hook",
            "transcript",
            "mode",
            "timeout_seconds",
            "cwd",
            "hit_if_all_true",
            "on_hit",
            "prompt",
        })
        self.assertEqual(self.enqueued[0]["hook"], "unverified-tag-check")
        self.assertEqual(self.enqueued[0]["transcript"], path)
        self.assertIn("DO1's repair worker is off or stuck", self.enqueued[0]["on_hit"])

    def test_hit_job_uses_investigate_mode(self):
        self.check(POSITIVE_ONE)
        job = self.enqueued[0]
        self.assertEqual(job["mode"], "investigate")
        self.assertEqual(job["timeout_seconds"], 300)
        self.assertEqual(job["hit_if_all_true"], [])
        self.assertIn('"blocker_false": true|false', job["prompt"])
        self.assertIn('"claim_status": "true"|"false"|"unknown"', job["prompt"])
        self.assertIn('"report"', job["prompt"])

    def test_hit_reads_last_assistant_text_from_transcript(self):
        path = self.write_transcript(POSITIVE_ONE)
        ids = detect.check_reply({"transcript_path": path, "cwd": self.tmp.name})
        self.assertEqual(len(ids), 1)
        self.assertEqual(len(self.enqueued), 1)

    def test_hit_expired_state_entry_gets_checked_again(self):
        path = self.write_transcript()
        os.makedirs(self.detector_state, exist_ok=True)
        with open(detect.state_path(path), "w", encoding="utf-8") as handle:
            json.dump({"do1 s repair worker is off or stuck": time.time() - 7201}, handle)
        self.check(POSITIVE_ONE, path)
        self.assertEqual(len(self.enqueued), 1)

    def test_silent_malformed_tag_with_no_reason(self):
        self.check("{{CAT-UNVERIFIED: claim -- cannot verify: }}")
        self.assertEqual(self.enqueued, [])

    def test_silent_tag_inside_closed_fence(self):
        self.check(f"```text\n{POSITIVE_ONE}\n```")
        self.assertEqual(self.enqueued, [])

    def test_silent_tag_inside_inline_code(self):
        self.check(f"`{POSITIVE_ONE}`")
        self.assertEqual(self.enqueued, [])

    def test_silent_same_claim_twice_in_one_transcript(self):
        path = self.write_transcript()
        self.check(POSITIVE_ONE, path)
        self.enqueued.clear()
        self.check(POSITIVE_ONE, path)
        self.assertEqual(self.enqueued, [])

    def test_silent_reply_with_no_tag(self):
        self.check("I could not check this one.")
        self.assertEqual(self.enqueued, [])

    def test_silent_fourth_tag_in_one_reply(self):
        text = "\n".join(
            f"{{{{CAT-UNVERIFIED: claim {index} -- cannot verify: blocker {index}}}}}"
            for index in range(4)
        )
        self.check(text)
        self.assertEqual(len(self.enqueued), 3)
        self.assertNotIn("claim 3", "\n".join(job["on_hit"] for job in self.enqueued))

    def test_unreadable_state_file_reads_as_empty(self):
        path = self.write_transcript()
        os.makedirs(self.detector_state, exist_ok=True)
        state_path = detect.state_path(path)
        with open(state_path, "w", encoding="utf-8") as handle:
            json.dump({"do1 s repair worker is off or stuck": time.time()}, handle)
        os.chmod(state_path, 0)
        try:
            self.check(POSITIVE_ONE, path)
        finally:
            os.chmod(state_path, stat.S_IRUSR | stat.S_IWUSR)
        self.assertEqual(len(self.enqueued), 1)

    def test_missing_transcript_hands_off_nothing(self):
        err = io.StringIO()
        missing = os.path.join(self.tmp.name, "missing.jsonl")
        with contextlib.redirect_stderr(err):
            ids = detect.check_reply({"transcript_path": missing, "last_assistant_message": POSITIVE_ONE})
        self.assertEqual(ids, [])
        self.assertEqual(self.enqueued, [])
        self.assertIn("unverified-tag-check: no transcript, reply not checked", err.getvalue())

    def test_entry_script_exits_zero_on_malformed_stdin(self):
        for module in (claude_stop_check, cursor_session):
            err = io.StringIO()
            out = io.StringIO()
            with patch.object(sys, "stdin", io.StringIO("not-json")):
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    module.main()
            self.assertIn("catstack-hook-error unverified-tag-check: JSONDecodeError:", err.getvalue())
        err = io.StringIO()
        with patch.object(sys, "argv", ["codex_notify.py", "not-json"]):
            with contextlib.redirect_stderr(err):
                codex_notify.main()
        self.assertIn("catstack-hook-error unverified-tag-check: JSONDecodeError:", err.getvalue())


if __name__ == "__main__":
    unittest.main()
