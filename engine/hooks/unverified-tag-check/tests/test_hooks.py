from __future__ import annotations

import io
import json
import os
import stat
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOKS_DIR)

import claude_stop_check  # noqa: E402
import codex_notify  # noqa: E402
import cursor_session  # noqa: E402
import detect  # noqa: E402

sys.path.append(os.path.join(os.path.dirname(HOOKS_DIR), "llm-judge"))
from judge_test_base import JudgeTestCase  # noqa: E402


POSITIVE_ONE = "{{CAT-UNVERIFIED: DO1's repair worker is off or stuck -- cannot verify: can't log in to DO1 to look}}"
POSITIVE_TWO = "{{CAT-UNVERIFIED: the fixed `pnpm` command ran instead of the repo's own setup command -- cannot verify: I did not read Invoker's code}}"


class FakeJudge:
    def __init__(self):
        self.jobs = []

    def enqueue(self, job):
        self.jobs.append(job)
        return job["id"]


def transcript_row(role: str, text: str) -> str:
    return json.dumps({"type": role, "message": {"role": role, "content": [{"type": "text", "text": text}]}})


class TestUnverifiedTagCheck(JudgeTestCase):
    def setUp(self):
        super().setUp()
        self.local = tempfile.TemporaryDirectory()
        self.tag_state = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            "CATSTACK_LLM_JUDGE_STATE_DIR": self.state.name,
            "CATSTACK_UNVERIFIED_TAG_CHECK_STATE_DIR": self.tag_state.name,
        })
        self.env.start()
        self.fake_judge = FakeJudge()
        self.judge_patch = patch.object(detect, "_judge", return_value=self.fake_judge)
        self.judge_patch.start()

    def tearDown(self):
        self.judge_patch.stop()
        self.env.stop()
        self.local.cleanup()
        self.tag_state.cleanup()
        super().tearDown()

    def write_transcript(self, text: str, name: str = "session.jsonl") -> str:
        path = os.path.join(self.local.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(transcript_row("assistant", text) + "\n")
        return path

    def payload(self, text: str, name: str = "session.jsonl") -> dict:
        path = self.write_transcript(text, name)
        return {"transcript_path": path, "last_assistant_message": text, "cwd": self.local.name}

    def test_hit_one_job_per_tag(self):
        ids = detect.check_reply(self.payload(f"First. {POSITIVE_ONE}\nSecond. {POSITIVE_TWO}"))
        self.assertEqual(ids, [job["id"] for job in self.fake_judge.jobs])
        self.assertEqual(len(self.fake_judge.jobs), 2)
        self.assertIn("DO1's repair worker is off or stuck", self.fake_judge.jobs[0]["prompt"])
        self.assertIn("the fixed `pnpm` command ran", self.fake_judge.jobs[1]["prompt"])

    def test_hit_job_uses_investigate_mode(self):
        payload = self.payload(f"Status: {POSITIVE_ONE}", "investigate.jsonl")
        [job_id] = detect.check_reply(payload)
        [job] = self.fake_judge.jobs
        self.assertEqual(job["id"], job_id)
        self.assertEqual(job["hook"], "unverified-tag-check")
        self.assertEqual(job["transcript"], payload["transcript_path"])
        self.assertEqual(job["mode"], "investigate")
        self.assertEqual(job["timeout_seconds"], 300)
        self.assertEqual(job["cwd"], self.local.name)
        self.assertEqual(job["hit_if_all_true"], [])
        self.assertIn('checked "DO1', job["on_hit"])
        self.assertIn('"blocker_false": true|false', job["prompt"])
        self.assertIn('"claim_status": "true"|"false"|"unknown"', job["prompt"])
        self.assertIn('"report"', job["prompt"])
        self.assertLess(len(job["prompt"]), 8000)

    def test_hit_falls_back_to_last_assistant_transcript_text(self):
        path = self.write_transcript(f"Fallback {POSITIVE_ONE}", "fallback.jsonl")
        ids = detect.check_reply({"transcript_path": path, "cwd": self.local.name})
        self.assertEqual(len(ids), 1)
        self.assertEqual(len(self.fake_judge.jobs), 1)

    def test_silent_malformed_tag_with_no_reason(self):
        text = "{{CAT-UNVERIFIED: the service is down}}"
        self.assertEqual(detect.check_reply(self.payload(text)), [])
        self.assertEqual(self.fake_judge.jobs, [])

    def test_silent_tag_inside_closed_fence(self):
        text = f"```text\n{POSITIVE_ONE}\n```\nOutside is clean."
        self.assertEqual(detect.check_reply(self.payload(text)), [])
        self.assertEqual(self.fake_judge.jobs, [])

    def test_silent_tag_inside_inline_code(self):
        text = f"Literal `{POSITIVE_ONE}` only."
        self.assertEqual(detect.check_reply(self.payload(text)), [])
        self.assertEqual(self.fake_judge.jobs, [])

    def test_silent_same_claim_twice_in_one_transcript(self):
        first = self.payload(POSITIVE_ONE, "same.jsonl")
        self.assertEqual(len(detect.check_reply(first)), 1)
        second = self.payload("Later " + POSITIVE_ONE, "same.jsonl")
        self.assertEqual(detect.check_reply(second), [])
        self.assertEqual(len(self.fake_judge.jobs), 1)

    def test_silent_reply_with_no_tag(self):
        self.assertEqual(detect.check_reply(self.payload("Verified with a real command.")), [])
        self.assertEqual(self.fake_judge.jobs, [])

    def test_silent_fourth_tag_in_one_reply(self):
        texts = [
            "{{CAT-UNVERIFIED: one -- cannot verify: a}}",
            "{{CAT-UNVERIFIED: two -- cannot verify: b}}",
            "{{CAT-UNVERIFIED: three -- cannot verify: c}}",
            "{{CAT-UNVERIFIED: four -- cannot verify: d}}",
        ]
        detect.check_reply(self.payload("\n".join(texts)))
        self.assertEqual(len(self.fake_judge.jobs), 3)
        prompts = "\n".join(job["prompt"] for job in self.fake_judge.jobs)
        self.assertNotIn("Claim: four.", prompts)

    def test_unreadable_state_file_reads_as_empty(self):
        path = self.write_transcript(POSITIVE_ONE, "state.jsonl")
        state_path = detect.state_path(path)
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        with open(state_path, "w", encoding="utf-8") as handle:
            handle.write("[")
        ids = detect.check_reply({"transcript_path": path, "last_assistant_message": POSITIVE_ONE})
        self.assertEqual(len(ids), 1)
        self.assertEqual(len(self.fake_judge.jobs), 1)

    def test_missing_transcript_hands_off_nothing(self):
        err = io.StringIO()
        missing = os.path.join(self.local.name, "missing.jsonl")
        with redirect_stderr(err):
            got = detect.check_reply({"transcript_path": missing, "last_assistant_message": POSITIVE_ONE})
        self.assertEqual(got, [])
        self.assertEqual(self.fake_judge.jobs, [])
        self.assertIn("unverified-tag-check: no transcript, reply not checked", err.getvalue())

    def test_unwritable_state_folder_still_hits(self):
        if os.geteuid() == 0:
            self.skipTest("root can write through permission bits")
        path = self.write_transcript(POSITIVE_ONE, "unwritable.jsonl")
        locked = os.path.join(self.local.name, "locked")
        os.mkdir(locked)
        os.chmod(locked, stat.S_IREAD | stat.S_IEXEC)
        err = io.StringIO()
        try:
            with patch.dict(os.environ, {"CATSTACK_UNVERIFIED_TAG_CHECK_STATE_DIR": locked}):
                with redirect_stderr(err):
                    ids = detect.check_reply({"transcript_path": path, "last_assistant_message": POSITIVE_ONE})
        finally:
            os.chmod(locked, stat.S_IREAD | stat.S_IWRITE | stat.S_IEXEC)
        self.assertEqual(len(ids), 1)
        self.assertIn("unverified-tag-check: could not write state", err.getvalue())

    def test_entry_script_exits_zero_on_malformed_stdin(self):
        for module in (claude_stop_check, cursor_session):
            with self.subTest(module=module.__name__):
                out = io.StringIO()
                err = io.StringIO()
                with patch.object(sys, "stdin", io.StringIO("not-json")):
                    with redirect_stdout(out), redirect_stderr(err):
                        module.main()
                if module is cursor_session:
                    self.assertEqual(json.loads(out.getvalue()), {"followup_message": ""})
                self.assertEqual(err.getvalue(), "")
        err = io.StringIO()
        with patch.object(sys, "argv", ["codex_notify.py", "not-json"]):
            with redirect_stderr(err):
                codex_notify.main()
        self.assertEqual(err.getvalue(), "")

    def test_no_hit_expired_claim_is_checked_again(self):
        path = self.write_transcript(POSITIVE_ONE, "expired.jsonl")
        state_path = detect.state_path(path)
        old = time.time() - detect.STATE_TTL_SECONDS - 1
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        with open(state_path, "w", encoding="utf-8") as handle:
            json.dump({detect.normalize_claim("DO1's repair worker is off or stuck"): old}, handle)
        self.assertEqual(len(detect.check_reply({"transcript_path": path, "last_assistant_message": POSITIVE_ONE})), 1)


if __name__ == "__main__":
    unittest.main()
