#!/usr/bin/env python3
"""Tests for artifact-watch-rearm.

Run: python3 -m unittest discover -s engine/hooks/artifact-watch-rearm/tests -v

Transcript rows copy the shapes of the real session that lost its watch: an Artifact
tool_use with only file_path, and a user tool_result whose text reads "Published ... at <url>".
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HOOK_DIR)))
sys.path.insert(0, HOOK_DIR)
sys.path.insert(0, os.path.join(REPO_ROOT, "engine", "hooks", "_sdk"))

import detect  # noqa: E402
import install_from_registry  # noqa: E402

ARTIFACT_ID = "7bRovPcTnWrPMu8VXJ5ykA"
OTHER_ID = "ZzOtherArtifact123456"
URL = f"https://claude.ai/artifact/{ARTIFACT_ID}"
OTHER_URL = f"https://claude.ai/artifact/{OTHER_ID}"
ENTRYPOINT = os.path.join(HOOK_DIR, "claude_rearm.py")


def publish_rows(tool_id: str, artifact_id: str = ARTIFACT_ID, url_input: str = "") -> list[dict]:
    tool_input = {"file_path": "/tmp/plan.html", "icon": "plan"}
    if url_input:
        tool_input["url"] = url_input
    return [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": tool_id, "name": "Artifact", "input": tool_input}]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tool_id,
             "content": f"Published /tmp/plan.html at https://claude.ai/artifact/{artifact_id} (Version 1, version id 1-abcd)\n\nLive subscription: arming in the background"}]}},
    ]


def read_rows(tool_id: str, artifact_id: str, header: str) -> list[dict]:
    return [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": tool_id, "name": "Artifact",
             "input": {"action": "read", "url": f"https://claude.ai/artifact/{artifact_id}"}}]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tool_id, "content": header + "\n<html></html>"}]}},
    ]


def user_row(text: str) -> dict:
    return {"type": "user", "message": {"role": "user", "content": text}}


def stop_watch_row(tool_id: str, url: str) -> dict:
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": tool_id, "name": "ArtifactComments",
         "input": {"action": "watch", "url": url, "on": False}}]}}


class HookCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state_dir = os.path.join(self.tmp.name, "state")
        self.previous_state_dir = detect.STATE_DIR
        detect.STATE_DIR = self.state_dir
        self.addCleanup(setattr, detect, "STATE_DIR", self.previous_state_dir)

    def transcript(self, rows: list, raw_lines: list[str] | None = None) -> str:
        path = os.path.join(self.tmp.name, "transcript.jsonl")
        lines = [json.dumps(row) for row in rows] + (raw_lines or [])
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        return path

    def event(self, path: str, name: str = "UserPromptSubmit", session: str = "s1", prompt: str = "") -> dict:
        payload = {"hook_event_name": name, "session_id": session, "transcript_path": path}
        if prompt:
            payload["prompt"] = prompt
        return payload


class DetectTests(HookCase):
    def test_published_artifact_fires_with_its_url(self):
        path = self.transcript(publish_rows("t1"))
        findings = detect.detect(self.event(path, "SessionStart"))
        self.assertEqual(len(findings), 1)
        self.assertIn(URL, findings[0].message)
        self.assertIn("action watch", findings[0].message)
        self.assertIn("replies true", findings[0].message)

    def test_publish_that_updates_by_url_fires(self):
        path = self.transcript(publish_rows("t1", url_input=URL))
        findings = detect.detect(self.event(path, "SessionStart"))
        self.assertEqual([f.subject for f in findings], [ARTIFACT_ID])

    def test_silent_when_transcript_has_no_artifact(self):
        path = self.transcript([user_row("hello"), {"type": "assistant", "message": {"role": "assistant", "content": []}}])
        self.assertEqual(detect.detect(self.event(path, "SessionStart")), [])

    def test_silent_when_publish_result_never_arrived(self):
        rows = publish_rows("t1")[:1]
        self.assertEqual(detect.detect(self.event(self.transcript(rows), "SessionStart")), [])

    def test_user_given_url_fires(self):
        path = self.transcript([user_row(f"please watch {OTHER_URL} for comments")])
        findings = detect.detect(self.event(path, "SessionStart"))
        self.assertEqual([f.subject for f in findings], [OTHER_ID])

    def test_url_in_the_prompt_being_submitted_fires(self):
        path = self.transcript([user_row("hi")])
        findings = detect.detect(self.event(path, prompt=f"look at {OTHER_URL}"))
        self.assertEqual([f.subject for f in findings], [OTHER_ID])

    def test_url_inside_system_reminder_is_ignored(self):
        path = self.transcript([user_row(f"<system-reminder>see {OTHER_URL}</system-reminder> hello")])
        self.assertEqual(detect.detect(self.event(path, "SessionStart")), [])

    def test_view_only_artifact_is_not_rearmed(self):
        rows = [user_row(f"look at {OTHER_URL}")] + read_rows(
            "r1", OTHER_ID, "[Artifact 1111 (version 2) — shared with you, view only; summary follows]")
        self.assertEqual(detect.detect(self.event(self.transcript(rows), "SessionStart")), [])

    def test_owned_by_you_read_counts_as_editable(self):
        rows = read_rows("r1", OTHER_ID, "[Artifact 1111 (version 2) — owned by you, private; raw HTML follows]")
        findings = detect.detect(self.event(self.transcript(rows), "SessionStart"))
        self.assertEqual([f.subject for f in findings], [OTHER_ID])

    def test_watch_the_user_stopped_is_not_rearmed(self):
        rows = publish_rows("t1") + [stop_watch_row("w1", URL)]
        self.assertEqual(detect.detect(self.event(self.transcript(rows), "SessionStart")), [])

    def test_two_artifacts_both_named_once(self):
        rows = publish_rows("t1") + publish_rows("t2", OTHER_ID)
        findings = detect.detect(self.event(self.transcript(rows), "SessionStart"))
        self.assertEqual(len(findings), 1)
        self.assertIn(URL, findings[0].message)
        self.assertIn(OTHER_URL, findings[0].message)


class OncePerSessionTests(HookCase):
    def test_second_prompt_with_same_set_is_silent(self):
        path = self.transcript(publish_rows("t1"))
        self.assertEqual(len(detect.detect(self.event(path))), 1)
        self.assertEqual(detect.detect(self.event(path)), [])

    def test_new_artifact_in_same_session_fires_again(self):
        path = self.transcript(publish_rows("t1"))
        self.assertEqual(len(detect.detect(self.event(path))), 1)
        path = self.transcript(publish_rows("t1") + publish_rows("t2", OTHER_ID))
        self.assertEqual(len(detect.detect(self.event(path))), 1)

    def test_session_start_after_restart_fires_again_for_same_set(self):
        path = self.transcript(publish_rows("t1"))
        self.assertEqual(len(detect.detect(self.event(path))), 1)
        self.assertEqual(len(detect.detect(self.event(path, "SessionStart"))), 1)
        self.assertEqual(detect.detect(self.event(path)), [])

    def test_other_session_is_not_silenced(self):
        path = self.transcript(publish_rows("t1"))
        self.assertEqual(len(detect.detect(self.event(path, session="a"))), 1)
        self.assertEqual(len(detect.detect(self.event(path, session="b"))), 1)


class UnreadableTests(HookCase):
    def test_unreadable_line_is_reported_with_context_and_counted(self):
        path = self.transcript(publish_rows("t1"), raw_lines=["{not json", "[1, 2]"])
        event = self.event(path, "SessionStart")
        findings = detect.detect(event)
        self.assertEqual([f.subject for f in findings], [ARTIFACT_ID])
        stderr = "\n".join(event["_catstack_stderr_lines"])
        self.assertIn(f"{path}:3: unreadable transcript line (JSONDecodeError", stderr)
        self.assertIn(f"{path}:4: unreadable transcript line (row is list", stderr)
        self.assertIn("2 unreadable line(s)", stderr)
        self.assertIn("2 unreadable line(s)", findings[0].evidence)

    def test_unreadable_transcript_file_is_reported_not_clean(self):
        event = self.event(os.path.join(self.tmp.name, "missing.jsonl"), "SessionStart")
        self.assertEqual(detect.detect(event), [])
        self.assertIn("cannot read transcript", "\n".join(event["_catstack_stderr_lines"]))

    def test_fresh_startup_missing_transcript_is_silent(self):
        event = {**self.event(os.path.join(self.tmp.name, "missing.jsonl"), "SessionStart"), "source": "startup"}
        self.assertEqual(detect.detect(event), [])
        self.assertEqual(event["_catstack_stderr_lines"], [])

    def test_resume_missing_transcript_is_reported_not_clean(self):
        event = {**self.event(os.path.join(self.tmp.name, "missing.jsonl"), "SessionStart"), "source": "resume"}
        self.assertEqual(detect.detect(event), [])
        self.assertIn("cannot read transcript", "\n".join(event["_catstack_stderr_lines"]))

    def test_payload_without_transcript_path_is_reported(self):
        event = {"hook_event_name": "SessionStart", "session_id": "s1"}
        self.assertEqual(detect.detect(event), [])
        self.assertIn("no transcript_path", "\n".join(event["_catstack_stderr_lines"]))


class EntrypointTests(HookCase):
    def run_entrypoint(self, payload: dict) -> subprocess.CompletedProcess:
        env = {**os.environ, "ARTIFACT_WATCH_REARM_STATE_DIR": self.state_dir,
               "CATSTACK_HOOK_METRICS_DIR": os.path.join(self.tmp.name, "metrics"), "HOME": self.tmp.name}
        return subprocess.run([sys.executable, ENTRYPOINT], input=json.dumps(payload),
                              capture_output=True, text=True, env=env, timeout=30)

    def test_session_start_emits_additional_context_naming_the_artifact(self):
        path = self.transcript(publish_rows("t1"))
        result = self.run_entrypoint(self.event(path, "SessionStart"))
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "SessionStart")
        self.assertIn(ARTIFACT_ID, output["additionalContext"])

    def test_entrypoint_prints_nothing_when_no_artifact(self):
        path = self.transcript([user_row("hello")])
        result = self.run_entrypoint(self.event(path, "SessionStart"))
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_entrypoint_reports_unreadable_line_on_stderr(self):
        path = self.transcript(publish_rows("t1"), raw_lines=["{bad"])
        result = self.run_entrypoint(self.event(path, "SessionStart"))
        self.assertIn("unreadable transcript line", result.stderr)


class InstallTests(unittest.TestCase):
    def test_hook_installs_for_claude_only(self):
        self.assertIn("artifact-watch-rearm", install_from_registry.harness_hook_names("claude"))
        for harness in ("cursor", "codex"):
            self.assertNotIn("artifact-watch-rearm", install_from_registry.harness_hook_names(harness))

    def test_claude_fragment_wires_both_events(self):
        with open(os.path.join(HOOK_DIR, "claude.hook.json"), encoding="utf-8") as handle:
            hooks = json.load(handle)["hooks"]
        self.assertEqual(sorted(hooks), ["SessionStart", "UserPromptSubmit"])
        self.assertEqual(hooks["SessionStart"][0]["matcher"], "startup|resume|clear|compact")


if __name__ == "__main__":
    unittest.main()
