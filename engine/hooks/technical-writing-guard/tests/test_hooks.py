#!/usr/bin/env python3
"""technical-writing-guard fires on a bad document and stays silent on chat.

Run: python3 -m unittest discover -s engine/hooks/technical-writing-guard/tests -v
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS_ROOT = os.path.dirname(HOOK_DIR)
REPO_DIR = os.path.dirname(os.path.dirname(HOOKS_ROOT))
SKILL_FIXTURES = os.path.join(
    HOOK_DIR, "..", "..", "..", "product", "skills", "technical-writing", "tests", "fixtures"
)
sys.path.insert(0, HOOK_DIR)

import detect  # noqa: E402


def _fixture(name: str) -> str:
    with open(os.path.join(SKILL_FIXTURES, name), encoding="utf-8") as handle:
        return handle.read()


BEFORE = None
AFTER = None


def setUpModule():
    global BEFORE, AFTER
    BEFORE = _fixture("before.md")
    AFTER = _fixture("after.md")


class TechnicalWritingGuard(unittest.TestCase):
    def test_readme_rewrite_of_the_bad_paragraph_fires(self):
        findings = detect.detect({
            "user_prompt": "Rewrite this README section so a tired engineer gets it on the first read.",
            "last_assistant_message": BEFORE,
        })
        self.assertGreaterEqual(len(findings), 2)
        messages = [item.message for item in findings]
        self.assertIn("passive setup: name who acts", messages)
        self.assertIn("metaphor noun: name the mechanism", messages)

    def test_good_rewrite_stays_silent(self):
        findings = detect.detect({
            "user_prompt": "Rewrite this README section.",
            "last_assistant_message": AFTER,
        })
        self.assertEqual(findings, [])

    def test_chat_question_stays_silent(self):
        findings = detect.detect({
            "user_prompt": "eli5 why is the deploy failing?",
            "last_assistant_message": BEFORE,
        })
        self.assertEqual(findings, [])

    def test_fenced_example_stays_silent(self):
        findings = detect.detect({
            "user_prompt": "Rewrite this README section.",
            "last_assistant_message": "The bad draft was:\n```\n" + BEFORE + "\n```\n",
        })
        self.assertEqual(findings, [])

    def test_backticked_ratchet_stays_silent(self):
        findings = detect.detect({
            "user_prompt": "Rewrite this README section.",
            "last_assistant_message": "Drop the word `ratchet` from the page.",
        })
        self.assertEqual(findings, [])

    def test_missing_user_prompt_fails_open(self):
        self.assertEqual(detect.detect({"last_assistant_message": BEFORE}), [])

    def test_unreadable_reply_is_unchecked(self):
        findings = detect.detect({
            "user_prompt": "Rewrite this README section.",
            "last_assistant_message": None,
        })
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule_id, "technical-writing-guard.unchecked")

    def _transcript(self, user: str, assistant: str) -> str:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = os.path.join(folder.name, "session.jsonl")
        rows = [
            {"role": "user", "message": {"content": [{"type": "text", "text": user}]}},
            {"role": "assistant", "message": {"content": [{"type": "text", "text": assistant}]}},
        ]
        with open(path, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
        return path

    def test_cursor_stop_payload_of_the_bad_paragraph_fires(self):
        findings = detect.detect({
            "status": "completed",
            "loop_count": 0,
            "transcript_path": self._transcript(
                "Rewrite this README section so a tired engineer gets it on the first read.",
                BEFORE,
            ),
        })
        self.assertGreaterEqual(len(findings), 2)

    def test_cursor_stop_payload_of_the_good_rewrite_stays_silent(self):
        findings = detect.detect({
            "status": "completed",
            "loop_count": 0,
            "transcript_path": self._transcript("Rewrite this README section.", AFTER),
        })
        self.assertEqual(findings, [])

    def test_cursor_stop_payload_of_a_fenced_example_stays_silent(self):
        findings = detect.detect({
            "status": "completed",
            "loop_count": 0,
            "transcript_path": self._transcript(
                "Rewrite this README section.",
                "The bad draft was:\n```\n" + BEFORE + "\n```\n",
            ),
        })
        self.assertEqual(findings, [])

    def test_cursor_stop_payload_of_a_backticked_word_stays_silent(self):
        findings = detect.detect({
            "status": "completed",
            "loop_count": 0,
            "transcript_path": self._transcript(
                "Rewrite this README section.",
                "Drop the word `ratchet` from the page.",
            ),
        })
        self.assertEqual(findings, [])

    def test_cursor_stop_payload_of_a_chat_question_stays_silent(self):
        findings = detect.detect({
            "status": "completed",
            "loop_count": 0,
            "transcript_path": self._transcript("eli5 why is the deploy failing?", BEFORE),
        })
        self.assertEqual(findings, [])

    def test_codex_payload_of_the_bad_paragraph_fires(self):
        findings = detect.detect({
            "input-messages": ["Rewrite this README section."],
            "last-assistant-message": BEFORE,
        })
        self.assertGreaterEqual(len(findings), 2)

    def test_codex_payload_of_a_chat_question_stays_silent(self):
        findings = detect.detect({
            "input-messages": ["eli5 why is the deploy failing?"],
            "last-assistant-message": BEFORE,
        })
        self.assertEqual(findings, [])

    def test_claude_reply_plus_transcript_ask_fires(self):
        findings = detect.detect({
            "last_assistant_message": BEFORE,
            "transcript_path": self._transcript("Rewrite this README section.", "ignored"),
        })
        self.assertGreaterEqual(len(findings), 2)

    def test_stop_hook_active_passes(self):
        findings = detect.detect({
            "stop_hook_active": True,
            "user_prompt": "Rewrite this README section.",
            "last_assistant_message": BEFORE,
        })
        self.assertEqual(findings, [])

    def test_grader_import_failure_is_unchecked_not_blocked(self):
        event = {
            "user_prompt": "Rewrite this README section.",
            "last_assistant_message": BEFORE,
        }
        with mock.patch.object(detect, "_grader", side_effect=ImportError("no grade_prose")):
            findings = detect.detect(event)
        self.assertEqual(findings, [])
        unchecked = event.get("_catstack_unchecked_findings")
        self.assertEqual(len(unchecked), 1)
        self.assertEqual(unchecked[0].rule_id, "technical-writing-guard.unchecked")

    def _snapshot_outside_the_repo(self) -> tuple[str, str]:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        snapshot = os.path.join(folder.name, ".cache", "catstack-hooks-snapshot")
        os.makedirs(snapshot)
        for name in ("_sdk", "_flags", "technical-writing-guard"):
            shutil.copytree(os.path.join(HOOKS_ROOT, name), os.path.join(snapshot, name))
        shutil.copy(os.path.join(HOOKS_ROOT, "hooks.toml"), snapshot)
        with open(os.path.join(snapshot, ".catstack-source"), "w", encoding="utf-8") as handle:
            handle.write(REPO_DIR + "\nunknown\nmain\n")
        return folder.name, snapshot

    def _run_snapshot_stop(self, home: str, snapshot: str, reply: str) -> subprocess.CompletedProcess:
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": home,
            "CATSTACK_HOOK_METRICS_DIR": os.path.join(home, "metrics"),
        }
        payload = json.dumps({
            "hook_event_name": "Stop",
            "user_prompt": "Rewrite this README section so a tired engineer gets it on the first read.",
            "last_assistant_message": reply,
        })
        return subprocess.run(
            [sys.executable, os.path.join(snapshot, "technical-writing-guard", "claude_stop_check.py")],
            input=payload,
            capture_output=True,
            text=True,
            env=env,
            cwd=home,
            timeout=30,
        )

    def test_runs_from_a_snapshot_outside_the_repo(self):
        home, snapshot = self._snapshot_outside_the_repo()
        bad = self._run_snapshot_stop(home, snapshot, BEFORE)
        self.assertNotIn("could not load", bad.stderr, bad.stderr)
        self.assertEqual(bad.returncode, 2, bad.stderr)
        self.assertIn("passive setup", bad.stderr)
        good = self._run_snapshot_stop(home, snapshot, AFTER)
        self.assertNotIn("could not load", good.stderr, good.stderr)
        self.assertEqual(good.returncode, 0, good.stderr)


if __name__ == "__main__":
    unittest.main()
