from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import tempfile
import unittest

RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS_DIR = os.path.dirname(RUNNER_DIR)
RUNNER = os.path.join(RUNNER_DIR, "run.py")
sys.path.insert(0, RUNNER_DIR)

import run  # noqa: E402


def _fixture(hook: str, name: str) -> dict[str, object]:
    with open(os.path.join(HOOKS_DIR, hook, "tests", "fixtures", name), encoding="utf-8") as handle:
        return json.load(handle)[0]


def _stop_scripts() -> list[str]:
    found = []
    for path in sorted(glob.glob(os.path.join(HOOKS_DIR, "*", "claude.hook.json"))):
        with open(path, encoding="utf-8") as handle:
            config = json.load(handle)
        for entry in config.get("hooks", {}).get("Stop", []):
            for hook in entry.get("hooks", []):
                command = hook.get("command", "")
                parts = command.split("/.claude/hooks/", 1)
                if len(parts) == 2:
                    found.append(parts[1].split()[0])
    return found


class MachineDeliverableShape(unittest.TestCase):
    def test_json_object_array_and_single_fence_are_deliverables(self) -> None:
        for text in (
            '{"title": "x", "body": "The bug is that it failed because of y."}',
            '  [1, {"a": 2}]\n',
            '```json\n{"title": "x"}\n```',
            '```\n[{"a": 1}]\n```\n',
        ):
            with self.subTest(text=text):
                self.assertTrue(run.machine_deliverable(text))

    def test_prose_scalars_and_broken_json_are_not_deliverables(self) -> None:
        for text in (
            'Here is the PR.\n\n```json\n{"title": "x"}\n```',
            '{"title": "x"}\n\nThe final JSON is the deliverable.',
            '```json\n{"a": 1}\n```\n\n```json\n{"b": 2}\n```',
            '"just a string"',
            "42",
            "true",
            '{"title": "x",}',
            "```json\n{\"a\": 1}",
            "",
            None,
            {"title": "x"},
        ):
            with self.subTest(text=text):
                self.assertFalse(run.machine_deliverable(text))


class RunnerSkipsJudgingAMachineDeliverable(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.metrics = os.path.join(self.tmp.name, "metrics")
        self.env = os.environ.copy()
        self.env.update({
            "CATSTACK_HOOK_METRICS_DIR": self.metrics,
            "CATSTACK_HOOK_REMINDER_STATE_DIR": os.path.join(self.tmp.name, "reminders"),
            "DIU_PLAIN_WORDS_WAIT_SECONDS": "0",
        })

    def _transcript(self, lines: list[object]) -> str:
        path = os.path.join(self.tmp.name, f"t{len(os.listdir(self.tmp.name))}.jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            for line in lines:
                handle.write(json.dumps(line) + "\n")
        return path

    def _payload(self, reply: str, transcript: str, event: str = "Stop") -> bytes:
        return json.dumps({
            "hook_event_name": event,
            "session_id": "deliverable-test",
            "transcript_path": transcript,
            "stop_hook_active": False,
            "last_assistant_message": reply,
        }).encode()

    def _through_runner(self, script: str, stdin: bytes) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [sys.executable, RUNNER, "--timeout", "30", script],
            input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env, timeout=60,
        )

    def _direct(self, script: str, stdin: bytes) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [sys.executable, os.path.join(HOOKS_DIR, script)],
            input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env, timeout=60,
        )

    def _last_row(self) -> dict[str, object]:
        with open(os.path.join(self.metrics, "runs.jsonl"), encoding="utf-8") as handle:
            return json.loads(handle.readlines()[-1])

    def _cases(self) -> list[tuple[str, str, str, str, bool]]:
        wait = _fixture("wait-needs-wakeup", "wait_replies_fires.json")
        return [
            ("diu-stop/claude_stop_check.py", str(_fixture("diu-stop", "claims_fires.json")["reply"]), "", "root cause", True),
            ("wait-needs-wakeup/claude_stop_check.py", str(wait["reply"]),
             self._transcript(list(wait["transcript"])), "wait-needs-wakeup", True),
            ("hedge-runs-prove-it/claude_stop_check.py",
             "It's probably still on the branch and I don't think the build ran.",
             self._transcript([]), "probably", False),
            ("handoff-needs-smoke-test/claude_stop_check.py",
             "Run `! bash /tmp/demo-login.sh` and I will check the result.",
             self._transcript([]), "handoff-needs-smoke-test", True),
        ]

    def test_json_only_reply_gets_no_feedback_from_each_prose_judge(self) -> None:
        for script, prose, transcript, marker, fires_on_json in self._cases():
            reply = json.dumps({"title": "Publish", "body": prose})
            with self.subTest(script=script):
                direct = self._direct(script, self._payload(reply, transcript))
                if fires_on_json:
                    self.assertEqual(direct.returncode, 2, direct.stderr.decode())
                    self.assertIn(marker, direct.stderr.decode())
                else:
                    self.assertEqual(direct.returncode, 0, direct.stderr.decode())
                ran = self._through_runner(script, self._payload(reply, transcript))
                self.assertEqual((ran.returncode, ran.stdout, ran.stderr), (0, b"", b""))
                row = self._last_row()
                self.assertEqual(row["skipped"], "machine-deliverable")
                self.assertEqual(row["outcome"], "silent")

    def test_fenced_json_only_reply_gets_no_feedback(self) -> None:
        script, prose, transcript, _marker, _fires = self._cases()[0]
        reply = "```json\n" + json.dumps({"body": prose}) + "\n```"
        ran = self._through_runner(script, self._payload(reply, transcript))
        self.assertEqual((ran.returncode, ran.stdout, ran.stderr), (0, b"", b""))

    def test_prose_reply_with_a_json_snippet_is_still_judged_by_each_hook(self) -> None:
        for script, prose, transcript, marker, _fires in self._cases():
            reply = prose + '\n\n```json\n{"title": "Publish"}\n```\n'
            with self.subTest(script=script):
                ran = self._through_runner(script, self._payload(reply, transcript))
                self.assertEqual(ran.returncode, 2, ran.stderr.decode())
                self.assertIn(marker, ran.stderr.decode())
                self.assertNotIn("skipped", self._last_row())

    def test_every_installed_stop_hook_is_skipped_on_a_json_only_reply(self) -> None:
        scripts = _stop_scripts()
        self.assertGreaterEqual(len(scripts), 19)
        reply = json.dumps({"title": "Publish", "body": "The bug is that it failed because of y."})
        for script in scripts:
            with self.subTest(script=script):
                ran = self._through_runner(script, self._payload(reply, self._transcript([])))
                self.assertEqual((ran.returncode, ran.stdout, ran.stderr), (0, b"", b""))
                self.assertEqual(self._last_row()["skipped"], "machine-deliverable")

    def test_non_reply_event_with_json_text_still_runs_the_hook(self) -> None:
        script, prose, transcript, marker, _fires = self._cases()[0]
        reply = json.dumps({"body": prose})
        ran = self._through_runner(script, self._payload(reply, transcript, event="UserPromptSubmit"))
        self.assertNotIn("skipped", self._last_row())
        self.assertIn(marker, (ran.stdout + ran.stderr).decode())

    def test_unreadable_payload_runs_the_hook_instead_of_skipping(self) -> None:
        ran = self._through_runner("diu-stop/claude_stop_check.py", b"not json {")
        self.assertNotIn("skipped", self._last_row())
        self.assertIn(b"catstack-hook-error diu-stop", ran.stderr)


if __name__ == "__main__":
    unittest.main()
