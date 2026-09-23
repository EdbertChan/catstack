from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
import unittest
import warnings
from contextlib import redirect_stderr
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOK_DIR)

import claude_stop_check
import detect
import install_claude_hook

sys.path.append(os.path.dirname(detect.LLM_JUDGE_PATH))
import inbox as judge_inbox
import phrases
from judge_test_base import JudgeTestCase


PY = sys.executable
SETUP_REPLY = "Please run: invoker-cli setup slack ... then tell me when it completes."
XCODE_REPLY = "Simulator build still passes. Now on your end in Xcode:"
PERMISSION_REPLY = "The setup is waiting for you to approve the permission prompt."
OAUTH_REPLY = "Open the browser and complete OAuth consent, then tell me when it finishes."
HIT = json.dumps({"match": True, "closest": SETUP_REPLY})
CLEAN = json.dumps({"match": False, "closest": ""})
ANSWERS_HIT = ["fake", [PY, "-c", f"print({HIT!r})", "{prompt}"]]
ANSWERS_CLEAN = ["fake", [PY, "-c", f"print({CLEAN!r})", "{prompt}"]]
MISSING = ["ghost", ["catstack-llm-judge-no-such-binary", "{prompt}"]]


def text_line(role: str, text: str) -> dict:
    return {"type": role, "message": {"role": role, "content": [{"type": "text", "text": text}]}}


def tool_use(tool_id: str, command: str) -> dict:
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": [{
            "type": "tool_use",
            "id": tool_id,
            "name": "Bash",
            "input": {"command": command},
        }]},
    }


def tool_result(tool_id: str, result: str, is_error: bool = False) -> dict:
    return {
        "type": "user",
        "message": {"role": "user", "content": [{
            "type": "tool_result",
            "tool_use_id": tool_id,
            "content": result,
            "is_error": is_error,
        }]},
    }


class TestHandbackNeedsAttempt(JudgeTestCase):
    def setUp(self):
        super().setUp()
        self.work = tempfile.TemporaryDirectory()
        self.hook_state = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            "HANDBACK_NEEDS_ATTEMPT_STATE_DIR": self.hook_state.name,
        })
        self.env.start()
        detect.STATE_DIR = self.hook_state.name
        detect._judge.cache_clear()
        detect._phrases.cache_clear()
        caught = warnings.catch_warnings()
        caught.__enter__()
        self.addCleanup(caught.__exit__, None, None, None)
        warnings.simplefilter("ignore", ResourceWarning)

    def tearDown(self):
        deadline = time.monotonic() + 15
        while self.jobs() and time.monotonic() < deadline:
            time.sleep(0.1)
        detect._judge.cache_clear()
        detect._phrases.cache_clear()
        self.env.stop()
        self.hook_state.cleanup()
        self.work.cleanup()
        super().tearDown()

    def jobs(self) -> list[str]:
        folder = os.path.join(self.state.name, "jobs")
        return os.listdir(folder) if os.path.isdir(folder) else []

    def write_transcript(self, rows: list[dict], name: str = "session.jsonl") -> str:
        path = os.path.join(self.work.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
        return path

    def wait_for_job(self, count: int = 1) -> dict:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            jobs = self.jobs()
            if len(jobs) == count:
                with open(os.path.join(self.state.name, "jobs", jobs[0]), encoding="utf-8") as handle:
                    return json.load(handle)
            time.sleep(0.05)
        self.fail(f"expected {count} judge job(s), found {self.jobs()}")

    def wait_for_messages(self, path: str) -> list[str]:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            messages = judge_inbox.messages(path)
            if messages:
                return messages
            time.sleep(0.1)
        return []

    def wait_for_clean(self, path: str) -> list[str]:
        deadline = time.monotonic() + 5
        while self.jobs() and time.monotonic() < deadline:
            time.sleep(0.05)
        return judge_inbox.messages(path)

    def enqueue(self, reply: str, rows: list[dict] | None = None) -> tuple[str, dict]:
        rows = rows or [text_line("user", "Please help with this."), text_line("assistant", reply)]
        path = self.write_transcript(rows)
        job_id = detect.enqueue_judge({"transcript_path": path, "last_assistant_message": reply})
        self.assertIsNotNone(job_id)
        return path, self.wait_for_job()

    def test_dictionary_loads_exchange_examples(self):
        dictionary = phrases.load("handback-needs-attempt")
        self.assertEqual(dictionary["checker"], "handback-needs-attempt")
        self.assertEqual(dictionary["reads"], "exchange")
        self.assertIn(SETUP_REPLY, dictionary["match"])
        self.assertIn("permission prompt", " ".join(dictionary["not_match"]))
        self.assertEqual(dictionary["on_hit"], detect.FOLLOWUP)

    def test_flags_invoker_setup_handback_without_attempt(self):
        self.use_runners(ANSWERS_HIT)
        path, job = self.enqueue(SETUP_REPLY)
        self.assertEqual(job["hook"], "handback-needs-attempt")
        self.assertEqual(job["transcript"], path)
        self.assertIn(SETUP_REPLY, job["prompt"])
        self.assertIn("TURN TOOL CALLS AND RESULTS:\nnone", job["prompt"])
        self.assertEqual(self.wait_for_messages(path), [detect.FOLLOWUP])

    def test_flags_xcode_handback_without_attempt(self):
        self.use_runners(ANSWERS_HIT)
        path, _ = self.enqueue(XCODE_REPLY)
        self.assertEqual(self.wait_for_messages(path), [detect.FOLLOWUP])

    def test_prompt_contains_current_turn_tool_calls_and_results(self):
        self.use_runners(ANSWERS_CLEAN)
        reply = "The command was denied, so only you can approve it."
        rows = [
            text_line("user", "Set up Slack."),
            tool_use("tool-1", "invoker-cli setup slack --workspace acme"),
            tool_result("tool-1", "Permission denied by the sandbox", True),
            text_line("assistant", reply),
        ]
        path, job = self.enqueue(reply, rows)
        self.assertIn("invoker-cli setup slack --workspace acme", job["prompt"])
        self.assertIn("Permission denied by the sandbox", job["prompt"])
        self.assertEqual(self.wait_for_clean(path), [])

    def test_silent_after_permission_denial(self):
        self.use_runners(ANSWERS_CLEAN)
        rows = [
            text_line("user", "Set up Slack."),
            tool_use("tool-1", "invoker-cli setup slack"),
            tool_result("tool-1", "Permission denied by user", True),
            text_line("assistant", PERMISSION_REPLY),
        ]
        path, _ = self.enqueue(PERMISSION_REPLY, rows)
        self.assertEqual(self.wait_for_clean(path), [])

    def test_silent_for_oauth_consent_handback(self):
        self.use_runners(ANSWERS_CLEAN)
        rows = [
            text_line("user", "Connect the account."),
            tool_use("tool-1", "open https://provider.example/oauth"),
            tool_result("tool-1", "Browser opened; OAuth consent requires the account owner", False),
            text_line("assistant", OAUTH_REPLY),
        ]
        path, _ = self.enqueue(OAUTH_REPLY, rows)
        self.assertEqual(self.wait_for_clean(path), [])

    def test_silent_for_human_only_hardware_step(self):
        self.use_runners(ANSWERS_CLEAN)
        reply = "Plug the device into your computer and press its physical pairing button."
        path, _ = self.enqueue(reply, [text_line("user", "Pair the device."), text_line("assistant", reply)])
        self.assertEqual(self.wait_for_clean(path), [])

    def test_judge_failure_is_unchecked(self):
        self.use_runners(MISSING)
        path, _ = self.enqueue(SETUP_REPLY)
        messages = self.wait_for_messages(path)
        self.assertEqual(len(messages), 1)
        self.assertIn("could not judge", messages[0])

    def test_stop_hook_active_does_not_queue(self):
        path = self.write_transcript([text_line("assistant", SETUP_REPLY)])
        self.assertIsNone(detect.enqueue_judge({
            "transcript_path": path,
            "last_assistant_message": SETUP_REPLY,
            "stop_hook_active": True,
        }))
        self.assertEqual(self.jobs(), [])

    def test_prompted_state_expires(self):
        key = detect.reply_key("/tmp/session.jsonl", SETUP_REPLY)
        detect.mark_prompted(key)
        state_path = detect._state_file(key)
        os.utime(state_path, (time.time() - detect.STATE_TTL_SECONDS - 1,) * 2)
        self.assertFalse(detect.already_prompted(key))

    def test_unreadable_transcript_reports_unchecked(self):
        err = io.StringIO()
        with redirect_stderr(err):
            detect.try_enqueue_judge({
                "transcript_path": os.path.join(self.work.name, "missing.jsonl"),
                "last_assistant_message": SETUP_REPLY,
            })
        self.assertIn("unchecked", err.getvalue())
        self.assertIn("could not be read", err.getvalue())
        self.assertEqual(self.jobs(), [])

    def test_stop_entry_accepts_json_and_keeps_reply_unblocked(self):
        self.use_runners(ANSWERS_CLEAN)
        path = self.write_transcript([text_line("assistant", SETUP_REPLY)])
        with patch.object(sys, "stdin", io.StringIO(json.dumps({
            "transcript_path": path,
            "last_assistant_message": SETUP_REPLY,
        }))):
            claude_stop_check.main()
        self.assertEqual(len(self.jobs()), 1)


class TestInstallWiring(unittest.TestCase):
    def test_install_sh_wires_link_and_settings_merge(self):
        root = os.path.dirname(os.path.dirname(os.path.dirname(HOOK_DIR)))
        with open(os.path.join(root, "install.sh"), encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn('link_item "handback-needs-attempt" "$REPO_DIR/engine/hooks/handback-needs-attempt" "$HOME/.claude/hooks/handback-needs-attempt"', text)
        self.assertIn('python3 "$REPO_DIR/engine/hooks/handback-needs-attempt/install_claude_hook.py"', text)

    def test_manifest_wires_stop_only(self):
        with open(install_claude_hook.FRAGMENT_PATH, encoding="utf-8") as handle:
            fragment = json.load(handle)
        self.assertEqual(set(fragment["hooks"]), {"Stop"})
        command = fragment["hooks"]["Stop"][0]["hooks"][0]["command"]
        self.assertIn("handback-needs-attempt/claude_stop_check.py", command)

    def test_merge_is_idempotent_and_keeps_other_hooks(self):
        with open(install_claude_hook.FRAGMENT_PATH, encoding="utf-8") as handle:
            fragment = json.load(handle)
        other = {"matcher": "*", "hooks": [{"type": "command", "command": "python3 other/x.py"}]}
        settings = {"hooks": {"Stop": [other]}}
        self.assertTrue(install_claude_hook.merge_hook(settings, fragment))
        self.assertFalse(install_claude_hook.merge_hook(settings, fragment))
        self.assertEqual(settings["hooks"]["Stop"][0], other)
        self.assertEqual(len(settings["hooks"]["Stop"]), 2)


if __name__ == "__main__":
    unittest.main()
