#!/usr/bin/env python3
"""Tests for shipping offscope-session to Claude Code, Cursor, and Codex.

Run: python3 -m unittest discover -s engine/hooks/offscope-session/tests -v

Three things are pinned here, because a one-harness hook is invisible in the
other two and three copies of a detector drift:

  1. Each harness entrypoint calls the one shared `detect.detect`, and none of
     them carries detection logic of its own.
  2. One event does both halves, drain-then-enqueue. If a wrapper enqueued
     first it would drain the job it had just queued and answer the current
     turn's own prompt, which is the whole design gone.
  3. `./install.sh` reaches all three harnesses, and a second run changes
     nothing.

The conversation fixture, the fake model runners, and the transcript writer all
come from `test_hooks`, so the three harnesses are exercised against the same
pivot the detector tests use rather than against three private fixtures.
"""
from __future__ import annotations

import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
import unittest.mock
from contextlib import redirect_stderr

from test_hooks import HOOK_DIR, PIVOT, WORK_SO_FAR, OffscopeCase, write_transcript

sys.path.insert(0, HOOK_DIR)

import claude_prompt_submit  # noqa: E402
import codex_prompt_submit  # noqa: E402
import cursor_before_submit  # noqa: E402
import detect  # noqa: E402
import install_claude_hook  # noqa: E402
import install_codex_hook  # noqa: E402
import install_cursor_hook  # noqa: E402
import judge  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HOOK_DIR)))
INSTALL_SH = os.path.join(REPO_ROOT, "install.sh")
HOOKS_TOML = os.path.join(os.path.dirname(HOOK_DIR), "hooks.toml")

NON_HUMAN_PROMPT = "<task-notification>agent build-docs finished</task-notification>"

HARNESSES = {
    "claude": {
        "module": claude_prompt_submit,
        "entry": "claude_prompt_submit.py",
        "fragment": "claude.hook.json",
        "event": "UserPromptSubmit",
        "root": ".claude",
        "installer": install_claude_hook,
        "path_attr": "SETTINGS_PATH",
        "settings": ".claude/settings.json",
        "nested": True,
    },
    "cursor": {
        "module": cursor_before_submit,
        "entry": "cursor_before_submit.py",
        "fragment": "cursor.hook.json",
        "event": "beforeSubmitPrompt",
        "root": ".cursor",
        "installer": install_cursor_hook,
        "path_attr": "HOOKS_PATH",
        "settings": ".cursor/hooks.json",
        "nested": False,
    },
    "codex": {
        "module": codex_prompt_submit,
        "entry": "codex_prompt_submit.py",
        "fragment": "codex.hook.json",
        "event": "UserPromptSubmit",
        "root": ".codex",
        "installer": install_codex_hook,
        "path_attr": "HOOKS_PATH",
        "settings": ".codex/hooks.json",
        "nested": True,
    },
}

UNRELATED_NESTED = {"hooks": [{"type": "command", "command": "python3 /opt/someone-else/hook.py"}]}
UNRELATED_FLAT = {"command": "python3 /opt/someone-else/hook.py"}

PREVIOUS_VERDICT = {
    "id": "verdict-from-the-previous-turn",
    "hook": "offscope-session",
    "rule_id": "offscope-session.drift-hit",
    "outcome": "hit",
    "on_hit": "offscope-session: this prompt starts work with nothing left in common.",
    "reason": "all true: offscope",
    "answer": {"offscope": True, "why": "a different deliverable"},
}
SAME_TURN_MESSAGE = "a verdict about the prompt that asked for it"


def fragment(name: str) -> dict:
    with open(os.path.join(HOOK_DIR, name), encoding="utf-8") as handle:
        return json.load(handle)


def commands(fragment_hooks: dict, event: str, nested: bool) -> list[str]:
    entries = fragment_hooks.get(event, [])
    if not nested:
        return [str(entry.get("command", "")) for entry in entries]
    return [
        str(hook.get("command", ""))
        for entry in entries
        for hook in entry.get("hooks", [])
    ]


class SynchronousJudge:
    """A judge whose verdict is ready the instant the job is enqueued.

    The real judge answers in a detached process, so a wrapper that enqueued
    before draining would almost always still look correct. This one makes the
    wrong order visible: anything enqueued is immediately drainable, so a
    reversed wrapper hands back a verdict about the prompt it was just given.
    """

    def __init__(self, waiting):
        self.waiting = list(waiting)
        self.calls: list[str] = []

    def drain(self, transcript):
        self.calls.append("drain")
        taken, self.waiting = self.waiting, []
        return taken

    def enqueue(self, job):
        self.calls.append("enqueue")
        self.waiting.append({
            "id": job["id"],
            "outcome": "hit",
            "on_hit": SAME_TURN_MESSAGE,
            "reason": "all true: offscope",
            "answer": {"offscope": True, "why": "same turn"},
        })
        return job["id"]

    def is_subagent_payload(self, payload):
        return False


class TestOneSharedDetector(unittest.TestCase):
    def test_every_harness_entrypoint_calls_the_one_shared_detector(self):
        for name, spec in HARNESSES.items():
            with self.subTest(harness=name):
                self.assertIs(spec["module"].detect, detect.detect)

    def test_no_entrypoint_grows_its_own_detection_logic(self):
        for name, spec in HARNESSES.items():
            with self.subTest(harness=name):
                with open(os.path.join(HOOK_DIR, spec["entry"]), encoding="utf-8") as handle:
                    body = handle.read().split('"""')[-1]
                for forbidden in ("judge", "phrases", "running_scope", "build_job", "report(", "rule_id"):
                    self.assertNotIn(forbidden, body, f"{spec['entry']} should delegate, not decide")

    def test_each_entrypoint_names_its_own_harness_and_prompt_event(self):
        for name, spec in HARNESSES.items():
            with self.subTest(harness=name):
                with open(os.path.join(HOOK_DIR, spec["entry"]), encoding="utf-8") as handle:
                    body = handle.read()
                self.assertIn(f'"{name}"', body)
                self.assertIn(f'"{spec["event"]}"', body)
                self.assertIn('"offscope-session"', body)

    def test_the_cursor_event_name_is_one_the_detector_and_renderer_both_accept(self):
        self.assertIn(HARNESSES["cursor"]["event"], detect.PROMPT_EVENTS)
        for name, spec in HARNESSES.items():
            with self.subTest(harness=name):
                self.assertTrue(detect._is_prompt_event({"hook_event_name": spec["event"]}))


class TestDrainBeforeEnqueue(OffscopeCase):
    def test_the_previous_turn_is_reported_before_this_prompt_is_enqueued(self):
        fake = SynchronousJudge([PREVIOUS_VERDICT])
        with unittest.mock.patch.object(detect, "_judge", lambda: fake), redirect_stderr(io.StringIO()):
            findings = detect.detect(self.event(PIVOT))
        self.assertEqual(fake.calls, ["drain", "enqueue"])
        self.assertEqual([f.subject for f in findings], ["job:verdict-from-the-previous-turn"])
        self.assertNotIn(SAME_TURN_MESSAGE, "\n".join(f.message for f in findings))

    def test_each_harness_entrypoint_reports_the_waiting_verdict_and_enqueues_this_prompt(self):
        for name, spec in HARNESSES.items():
            with self.subTest(harness=name):
                rules, queued, still_waiting = self.run_entrypoint(spec)
                self.assertEqual(rules, ["offscope-session.drift-hit"])
                self.assertEqual(len(queued), 1, f"{name} queued {queued}")
                self.assertEqual(still_waiting, [], f"{name} reported a verdict but kept it")

    def test_each_harness_entrypoint_stays_silent_on_a_prompt_nobody_typed(self):
        for name, spec in HARNESSES.items():
            with self.subTest(harness=name):
                rules, queued, still_waiting = self.run_entrypoint(spec, prompt=NON_HUMAN_PROMPT)
                self.assertEqual(rules, [])
                self.assertEqual(queued, [])
                self.assertTrue(still_waiting, f"{name} threw away a verdict it never reported")

    def inbox(self, transcript):
        """(newly queued work, the seeded verdict if it is still waiting).

        `enqueue` writes the job file before it starts the detached judge, and
        the judge replaces that file with a verdict, so newly queued work is
        counted from the union of the two: either side of that handover is
        proof the question was asked. The seeded verdict is told apart by its
        own id, because a verdict left unreported is the opposite claim.
        """
        wanted = detect.channel(transcript)
        seeded = f"{PREVIOUS_VERDICT['id']}.json"
        queued, waiting = [], []
        jobs_dir = os.path.join(self.state.name, "jobs")
        for name in sorted(os.listdir(jobs_dir)) if os.path.isdir(jobs_dir) else []:
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(jobs_dir, name), encoding="utf-8") as handle:
                    job = json.load(handle)
            except (OSError, ValueError):
                continue
            if isinstance(job, dict) and job.get("transcript") == wanted:
                queued.append(f"job:{name}")
        folder = judge.verdict_dir(wanted)
        for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            if not name.endswith(".json"):
                continue
            (waiting if name == seeded else queued).append(f"verdict:{name}")
        return queued, waiting

    def run_entrypoint(self, spec, prompt=PIVOT):
        """Run one entrypoint for real; return (rule ids, queued work, unreported).

        Each harness gets its own transcript, so one harness's background judge
        cannot drop a verdict into the next harness's inbox. The waiting verdict
        is seeded rather than waited for, which makes the drain half
        deterministic; the enqueue half is the real one.
        """
        transcript = os.path.join(self.work.name, f"{spec['root']}-session.jsonl")
        write_transcript(transcript, WORK_SO_FAR)
        folder = judge.verdict_dir(detect.channel(transcript))
        os.makedirs(folder, exist_ok=True)
        seeded = dict(PREVIOUS_VERDICT, transcript=detect.channel(transcript))
        with open(os.path.join(folder, f"{seeded['id']}.json"), "w", encoding="utf-8") as handle:
            json.dump(seeded, handle)
        payload = {
            "hook_event_name": spec["event"],
            "prompt": prompt,
            "transcript_path": transcript,
            "session_id": "sess-three-harness",
        }
        with tempfile.TemporaryDirectory() as findings_dir:
            findings_file = os.path.join(findings_dir, "findings.json")
            env = dict(os.environ, CATSTACK_HOOK_FINDINGS_FILE=findings_file)
            env.pop(judge.CHILD_ENV, None)
            result = subprocess.run(
                [sys.executable, os.path.join(HOOK_DIR, spec["entry"])],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                timeout=60,
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            with open(findings_file, encoding="utf-8") as handle:
                rules = json.load(handle)
        queued, waiting = self.inbox(transcript)
        return rules, queued, waiting


class TestThreeHarnessFragments(unittest.TestCase):
    def test_each_fragment_points_at_its_own_harness_copy_of_the_shared_entrypoint(self):
        for name, spec in HARNESSES.items():
            with self.subTest(harness=name):
                found = commands(fragment(spec["fragment"])["hooks"], spec["event"], spec["nested"])
                self.assertEqual(
                    found,
                    [f"python3 $HOME/{spec['root']}/hooks/offscope-session/{spec['entry']}"],
                )

    def test_no_fragment_declares_a_tool_event(self):
        for name, spec in HARNESSES.items():
            with self.subTest(harness=name):
                self.assertEqual(set(fragment(spec["fragment"])["hooks"]), {spec["event"]})

    def test_install_sh_links_the_hook_and_runs_its_installer_for_all_three(self):
        with open(INSTALL_SH, encoding="utf-8") as handle:
            script = handle.read()
        for name, spec in HARNESSES.items():
            with self.subTest(harness=name):
                self.assertIn(
                    f'link_item "offscope-session" "$HOOKS_SNAPSHOT_DIR/offscope-session" '
                    f'"$HOME/{spec["root"]}/hooks/offscope-session"',
                    script,
                )
                self.assertIn(
                    f'python3 "$REPO_DIR/engine/hooks/offscope-session/install_{name}_hook.py"',
                    script,
                )

    def test_the_registry_keeps_the_hook_silent_in_every_harness(self):
        with open(HOOKS_TOML, "rb") as handle:
            registry = tomllib.load(handle)
        self.assertEqual(registry["hooks"]["offscope-session"]["mode"], "off")


class TestInstallersAreIdempotent(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        for spec in HARNESSES.values():
            module, attr = spec["installer"], spec["path_attr"]
            self.addCleanup(setattr, module, attr, getattr(module, attr))
            setattr(module, attr, os.path.join(self.home.name, spec["settings"]))

    def run_installer(self, spec):
        out = io.StringIO()
        with unittest.mock.patch("sys.stdout", out):
            spec["installer"].main()
        return out.getvalue()

    def read_settings(self, spec):
        with open(os.path.join(self.home.name, spec["settings"]), encoding="utf-8") as handle:
            return handle.read()

    def write_settings(self, spec, data):
        path = os.path.join(self.home.name, spec["settings"])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            if isinstance(data, str):
                handle.write(data)
            else:
                json.dump(data, handle)

    def test_a_first_run_registers_the_entrypoint_in_every_harness(self):
        for name, spec in HARNESSES.items():
            with self.subTest(harness=name):
                self.assertIn("merged", self.run_installer(spec))
                found = commands(json.loads(self.read_settings(spec))["hooks"], spec["event"], spec["nested"])
                self.assertEqual(
                    found, [f"python3 $HOME/{spec['root']}/hooks/offscope-session/{spec['entry']}"]
                )

    def test_a_second_run_leaves_the_harness_settings_file_unchanged(self):
        for name, spec in HARNESSES.items():
            with self.subTest(harness=name):
                self.run_installer(spec)
                first = self.read_settings(spec)
                message = self.run_installer(spec)
                self.assertIn("already up to date", message)
                self.assertEqual(first, self.read_settings(spec))

    def test_an_installer_never_disturbs_another_hook_entry(self):
        for name, spec in HARNESSES.items():
            with self.subTest(harness=name):
                other = copy.deepcopy(UNRELATED_NESTED if spec["nested"] else UNRELATED_FLAT)
                self.write_settings(spec, {"version": 1, "hooks": {spec["event"]: [other]}})
                self.run_installer(spec)
                entries = json.loads(self.read_settings(spec))["hooks"][spec["event"]]
                self.assertEqual(entries[0], other)
                self.assertEqual(len(entries), 2)

    def test_a_stale_entry_is_replaced_rather_than_duplicated(self):
        for name, spec in HARNESSES.items():
            with self.subTest(harness=name):
                self.run_installer(spec)
                data = json.loads(self.read_settings(spec))
                entry = data["hooks"][spec["event"]][0]
                target = entry["hooks"][0] if spec["nested"] else entry
                target["timeout"] = 1
                self.write_settings(spec, data)
                self.run_installer(spec)
                after = json.loads(self.read_settings(spec))
                self.assertEqual(len(after["hooks"][spec["event"]]), 1)
                self.assertEqual(len(commands(after["hooks"], spec["event"], spec["nested"])), 1)
                self.assertEqual(
                    after["hooks"][spec["event"]], fragment(spec["fragment"])["hooks"][spec["event"]]
                )

    def test_a_malformed_settings_file_is_not_silently_replaced(self):
        for name, spec in HARNESSES.items():
            with self.subTest(harness=name):
                self.write_settings(spec, "{not json")
                with self.assertRaises(json.JSONDecodeError):
                    self.run_installer(spec)
                self.assertEqual(self.read_settings(spec), "{not json")

    def test_a_cursor_symlink_becomes_a_real_merged_file(self):
        spec = HARNESSES["cursor"]
        source = os.path.join(self.home.name, "someone-elses-fragment.json")
        with open(source, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "hooks": {"stop": [UNRELATED_FLAT]}}, handle)
        path = os.path.join(self.home.name, spec["settings"])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        os.symlink(source, path)
        self.run_installer(spec)
        self.assertFalse(os.path.islink(path))
        self.assertEqual(json.loads(self.read_settings(spec))["hooks"]["stop"], [UNRELATED_FLAT])
        with open(source, encoding="utf-8") as handle:
            self.assertNotIn("offscope-session", handle.read())


if __name__ == "__main__":
    unittest.main()
