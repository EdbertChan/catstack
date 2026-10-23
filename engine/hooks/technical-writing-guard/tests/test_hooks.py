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

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS_ROOT = os.path.dirname(HOOK_DIR)
REPO_DIR = os.path.dirname(os.path.dirname(HOOKS_ROOT))
REPO_ROOT = os.path.abspath(os.path.join(HOOK_DIR, "..", "..", ".."))
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


SNAPSHOT_PROBE = """
import json, sys
sys.path.insert(0, sys.argv[1])
import detect
asked = "Rewrite this README section so a tired engineer gets it on the first read."
out = {}
for name, path in (("before", sys.argv[2]), ("after", sys.argv[3])):
    with open(path, encoding="utf-8") as handle:
        reply = handle.read()
    out[name] = [item.rule_id for item in detect.detect({"user_prompt": asked, "last_assistant_message": reply})]
print(json.dumps(out))
"""


class GraderFromInstalledSnapshot(unittest.TestCase):
    """install.sh copies this hook under ~/.cache, outside the checkout, and records
    the checkout in `.catstack-source`. The grader must be found through that
    record; walking up from the copied file lands in the home directory."""

    def _snapshot(self, tmp: str, record: bool) -> str:
        snapshot = os.path.join(tmp, "home", ".cache", "catstack-hooks-snapshot")
        for name in ("technical-writing-guard", "_sdk"):
            shutil.copytree(os.path.join(HOOK_DIR, "..", name), os.path.join(snapshot, name))
        if record:
            with open(os.path.join(snapshot, ".catstack-source"), "w", encoding="utf-8") as handle:
                handle.write(f"{REPO_ROOT}\nabc123\nmain\n")
        return os.path.join(snapshot, "technical-writing-guard")

    def _probe(self, hook_copy: str) -> dict:
        result = subprocess.run(
            [
                sys.executable, "-c", SNAPSHOT_PROBE, hook_copy,
                os.path.join(SKILL_FIXTURES, "before.md"),
                os.path.join(SKILL_FIXTURES, "after.md"),
            ],
            capture_output=True, text=True, check=False, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_snapshot_copy_outside_the_repo_loads_the_grader_from_the_recorded_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            found = self._probe(self._snapshot(tmp, record=True))
        self.assertEqual(found["after"], [])
        self.assertIn("technical-writing-guard.sentence", found["before"])
        self.assertNotIn("technical-writing-guard.unchecked", found["before"])

    def test_snapshot_copy_with_no_source_record_is_unchecked(self):
        with tempfile.TemporaryDirectory() as tmp:
            found = self._probe(self._snapshot(tmp, record=False))
        self.assertEqual(found["after"], ["technical-writing-guard.unchecked"])
        self.assertEqual(found["before"], ["technical-writing-guard.unchecked"])



class GraderLocation(unittest.TestCase):
    """The installed snapshot sits under ~/.cache, three folders up is not the repo; the grader must still load."""

    def _run_from_snapshot(self, home: str) -> list:
        import shutil
        import subprocess
        snapshot = os.path.join(home, ".cache", "catstack-hooks-snapshot")
        shutil.copytree(os.path.join(HOOK_DIR, "..", "_sdk"), os.path.join(snapshot, "_sdk"))
        hook = os.path.join(snapshot, "technical-writing-guard")
        os.makedirs(hook)
        shutil.copy(os.path.join(HOOK_DIR, "detect.py"), hook)
        event = {"user_prompt": "Rewrite this README section so a tired engineer gets it on the first read.",
                 "last_assistant_message": AFTER}
        code = ("import json, sys; sys.path.insert(0, %r); import detect; "
                "print(json.dumps([[f.rule_id, f.evidence] for f in detect.detect(json.loads(sys.argv[1]))]))" % hook)
        env = {**os.environ, "HOME": home}
        out = subprocess.run([sys.executable, "-c", code, json.dumps(event)], capture_output=True, text=True, env=env, check=True)
        return json.loads(out.stdout)

    def test_the_snapshot_copy_loads_the_grader_from_the_installed_skill(self):
        with tempfile.TemporaryDirectory() as home:
            scripts = os.path.join(home, ".claude", "skills", "technical-writing", "scripts")
            os.makedirs(os.path.dirname(scripts))
            os.symlink(os.path.join(HOOK_DIR, "..", "..", "..", "product", "skills", "technical-writing", "scripts"), scripts)
            self.assertEqual(self._run_from_snapshot(home), [])

    def test_the_snapshot_copy_names_the_folders_it_tried_when_no_skill_is_installed(self):
        with tempfile.TemporaryDirectory() as home:
            findings = self._run_from_snapshot(home)
            self.assertEqual([f[0] for f in findings], [detect.RULE_UNCHECKED])
            self.assertIn(os.path.join(home, ".claude", "skills", "technical-writing", "scripts"), findings[0][1])


if __name__ == "__main__":
    unittest.main()
