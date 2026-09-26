#!/usr/bin/env python3
"""Tests for the offscope-session handoff record and terminal spawn.

Run: python3 -m unittest discover -s engine/hooks/offscope-session/tests -v

Every terminal here is a stub script on a `PATH` holding nothing else, so no
test can open a real window or reach a real terminal emulator on the machine
running it. The stubs are `/bin/sh` scripts using builtins only, because the
restricted `PATH` is exactly what a real spawn would search.
"""
from __future__ import annotations

import io
import json
import os
import platform
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOK_DIR)

import spawn  # noqa: E402

PIVOT = "forget that for now. my laptop won't connect to the office wifi, help me debug that"
HOSTILE = "park it -- fix the $PATH in ~/.zshrc, it has 'quotes' and \"more\" in it"
HANDBACK_RE = re.compile(r"^! bash (\S+)$", re.MULTILINE)


class SpawnCase(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.state = tempfile.TemporaryDirectory()
        self.addCleanup(self.state.cleanup)
        self.repo = tempfile.TemporaryDirectory()
        self.addCleanup(self.repo.cleanup)
        os.makedirs(os.path.join(self.repo.name, ".git"))
        self.bin = tempfile.TemporaryDirectory()
        self.addCleanup(self.bin.cleanup)
        self.env = patch.dict(os.environ, {spawn.STATE_ENV: self.state.name, "PATH": self.bin.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        for key in (spawn.AUTOSPAWN_ENV, spawn.TERMINAL_ENV, "DISPLAY", "WAYLAND_DISPLAY"):
            os.environ.pop(key, None)
        wait = patch.object(spawn, "SPAWN_WAIT_SECONDS", 0.3)
        wait.start()
        self.addCleanup(wait.stop)

    def stub(self, name, body="exit 0"):
        """One fake program on the test `PATH`, built from shell builtins only."""
        path = os.path.join(self.bin.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(f"#!/bin/sh\n{body}\n")
        os.chmod(path, 0o755)
        return path

    def autospawn(self, value="on"):
        os.environ[spawn.AUTOSPAWN_ENV] = value

    def watch_popen(self):
        """Record every `Popen` call and still really run it, detached."""
        calls = []
        real = subprocess.Popen

        def fake(argv, **kwargs):
            proc = real(argv, **kwargs)
            calls.append({"argv": list(argv), "kwargs": kwargs, "proc": proc})
            self.addCleanup(self.reap, proc)
            return proc

        patched = patch.object(subprocess, "Popen", fake)
        patched.start()
        self.addCleanup(patched.stop)
        return calls

    def reap(self, proc):
        try:
            proc.kill()
            proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"test cleanup could not kill pid {proc.pid}: {exc}", file=sys.stderr)

    def verdict(self, **extra):
        payload = {
            "id": "handoff1",
            "hook": "offscope-session",
            "rule_id": "offscope-session.drift-hit",
            "outcome": "hit",
            "answer": {"offscope": True, "why": "a different deliverable"},
            "reason": "all true: offscope",
            spawn.REQUEST_KEY: PIVOT,
        }
        payload.update(extra)
        return payload

    def event(self, **extra):
        payload = {
            "hook_event_name": "UserPromptSubmit",
            "cwd": os.path.join(self.repo.name, "engine", "hooks"),
            "session_id": "sess-parent",
        }
        payload.update(extra)
        return payload

    def run_spawn(self, verdict=None, event=None):
        """One spawn, its single finding, and whatever it said on stderr."""
        err = io.StringIO()
        with redirect_stderr(err):
            findings = spawn.spawn(
                self.verdict() if verdict is None else verdict,
                self.event() if event is None else event,
            )
        self.assertEqual(len(findings), 1, f"expected exactly one finding, got {findings}")
        return findings[0], err.getvalue()

    def handback_path(self, message):
        found = HANDBACK_RE.findall(message)
        self.assertEqual(len(found), 1, f"expected exactly one '! bash <path>' line in: {message}")
        return found[0]


class TestHandoffRecord(SpawnCase):
    def test_the_handoff_file_is_written_and_parses_as_json(self):
        finding, _ = self.run_spawn()
        path = os.path.join(self.state.name, "handoffs", "handoff1.json")
        self.assertTrue(os.path.isfile(path), f"no handoff at {path}")
        with open(path, encoding="utf-8") as handle:
            record = json.load(handle)
        self.assertEqual(record["request"], PIVOT)
        self.assertEqual(record["repo_root"], self.repo.name)
        self.assertEqual(record["parent_session_id"], "sess-parent")
        self.assertEqual(record["harness"], "claude")
        self.assertEqual(record["reason"], "a different deliverable")
        self.assertEqual(record["rule_id"], "offscope-session.drift-hit")
        self.assertIn("handoff1", finding.subject)

    def test_the_handoff_names_the_harness_the_parent_session_runs(self):
        for event_name, harness in (
            ("UserPromptSubmit", "claude"),
            ("beforeSubmitPrompt", "cursor"),
            ("user_prompt_submit", "codex"),
        ):
            with self.subTest(harness=harness):
                record = spawn.handoff_record(self.verdict(), self.event(hook_event_name=event_name))
                self.assertEqual(record["harness"], harness)
        self.assertEqual(spawn.harness_name({"harness": "codex"}), "codex")

    def test_a_handoff_id_with_a_slash_or_a_leading_dot_is_refused(self):
        for bad in ("../escape", "a/b", ".hidden"):
            with self.subTest(handoff_id=bad):
                with self.assertRaises(ValueError):
                    spawn.plain_id(bad)
                with self.assertRaises(ValueError):
                    spawn.handoff_record(self.verdict(id=bad), self.event())

    def test_the_script_seeds_the_new_session_with_the_request_verbatim(self):
        """Run the script for real, with a stub harness, and read back its argument.

        Asserting on the script text cannot prove this: the request is shell
        quoted, so a quote-mangling bug would still leave the words in the
        file. What matters is the string the harness is finally handed.
        """
        seen = os.path.join(self.state.name, "seen.txt")
        self.stub("claude", f'printf %s "$1" > {shlex.quote(seen)}')
        self.run_spawn(verdict=self.verdict(**{spawn.REQUEST_KEY: HOSTILE}))
        script = os.path.join(self.state.name, "scripts", "handoff1.sh")
        with open(script, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn(f"cd {self.repo.name}", text)
        self.assertIn("exec claude ", text)
        self.assertTrue(os.access(script, os.X_OK), "the handback script is not executable")
        proc = subprocess.run(
            ["bash", script], capture_output=True, text=True,
            env={"PATH": os.pathsep.join([self.bin.name, "/usr/bin", "/bin"])},
        )
        self.assertEqual(proc.returncode, 0, f"the handback script failed: {proc.stderr}")
        with open(seen, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), HOSTILE)

    def test_a_verdict_with_no_request_is_spawn_unavailable_not_a_silent_pass(self):
        self.autospawn()
        self.stub("claude")
        self.stub("x-terminal-emulator")
        calls = self.watch_popen()
        verdict = self.verdict()
        verdict.pop(spawn.REQUEST_KEY)
        finding, err = self.run_spawn(verdict=verdict)
        self.assertEqual(finding.rule_id, "offscope-session.spawn-unavailable")
        self.assertIn("carried no off-scope request", finding.message)
        self.assertIn("carried no off-scope request", err)
        self.assertEqual(calls, [])


class TestAutospawnOff(SpawnCase):
    def test_the_flag_off_starts_no_process(self):
        self.stub("claude")
        self.stub("x-terminal-emulator")
        calls = self.watch_popen()
        finding, err = self.run_spawn()
        self.assertEqual(finding.rule_id, "offscope-session.spawn-disabled")
        self.assertEqual(calls, [], "auto-spawn is off, so nothing may be started")
        self.assertEqual(err, "")
        script = self.handback_path(finding.message)
        self.assertTrue(os.path.isfile(script), f"the handback script {script} is not on disk")
        self.assertIn(os.path.join(self.state.name, "handoffs", "handoff1.json"), finding.message)
        self.assertIn(spawn.AUTOSPAWN_ENV, finding.message)

    def test_a_flag_that_is_not_on_or_one_is_off(self):
        for value in ("", "off", "0", "yes", "true", "ON "):
            with self.subTest(value=value):
                os.environ[spawn.AUTOSPAWN_ENV] = value
                self.assertIs(spawn.autospawn_on(), value.strip().lower() in {"on", "1"})


class TestAutospawnOn(SpawnCase):
    def test_the_flag_on_starts_a_detached_process_with_start_new_session(self):
        self.autospawn()
        self.stub("claude")
        terminal = self.stub("x-terminal-emulator", 'echo "opened $*"')
        calls = self.watch_popen()
        finding, err = self.run_spawn()
        self.assertEqual(finding.rule_id, "offscope-session.spawn-started")
        self.assertEqual(len(calls), 1, f"expected one spawn, got {calls}")
        call = calls[0]
        self.assertEqual(call["argv"][0], terminal)
        self.assertEqual(call["argv"][1:3], ["-e", "bash"])
        self.assertEqual(call["kwargs"]["start_new_session"], True)
        self.assertEqual(call["kwargs"]["stdin"], subprocess.DEVNULL)
        self.assertEqual(call["kwargs"]["cwd"], self.repo.name)
        self.assertEqual(err, "")

    def test_the_terminals_output_goes_to_the_log_and_never_to_this_hooks_stderr(self):
        self.autospawn()
        self.stub("claude")
        self.stub("x-terminal-emulator", 'echo TERMINAL-SAID-THIS; echo TERMINAL-ERRORED >&2')
        finding, err = self.run_spawn()
        self.assertEqual(finding.rule_id, "offscope-session.spawn-started")
        self.assertEqual(err, "")
        with open(spawn.log_path(), encoding="utf-8") as handle:
            log = handle.read()
        self.assertIn("TERMINAL-SAID-THIS", log)
        self.assertIn("TERMINAL-ERRORED", log)
        self.assertIn("handoff handoff1", log)

    def test_a_terminal_that_stays_in_the_foreground_still_counts_as_started(self):
        self.autospawn()
        self.stub("claude")
        self.stub("xterm", "while : ; do : ; done")
        calls = self.watch_popen()
        finding, _ = self.run_spawn()
        self.assertEqual(finding.rule_id, "offscope-session.spawn-started")
        self.assertIsNone(calls[0]["proc"].poll(), "the window process should still be running")


class TestSpawnUnavailable(SpawnCase):
    def test_no_terminal_on_path_is_spawn_unavailable_with_a_runnable_handback_script(self):
        self.autospawn()
        self.stub("claude")
        calls = self.watch_popen()
        finding, err = self.run_spawn()
        self.assertEqual(finding.rule_id, "offscope-session.spawn-unavailable")
        self.assertIn("no terminal program is installed", finding.message)
        self.assertIn("not a detection failure", finding.message)
        self.assertIn("no terminal program is installed", err)
        self.assertEqual(calls, [])
        script = self.handback_path(finding.message)
        self.assertTrue(os.path.isfile(script), f"the handback script {script} is not on disk")
        proc = subprocess.run(["bash", "-n", script], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
        self.assertEqual(proc.returncode, 0, f"the handback script does not parse: {proc.stderr}")

    def test_a_terminal_that_exits_non_zero_is_spawn_unavailable(self):
        self.autospawn()
        self.stub("claude")
        self.stub("x-terminal-emulator", "exit 3")
        finding, err = self.run_spawn()
        self.assertEqual(finding.rule_id, "offscope-session.spawn-unavailable")
        self.assertIn("exited 3", finding.message)
        self.assertIn("exited 3", err)
        self.assertIn("handoff handoff1", err)
        self.assertIn("x-terminal-emulator", err)
        self.handback_path(finding.message)

    def test_a_missing_harness_command_is_spawn_unavailable(self):
        self.autospawn()
        self.stub("x-terminal-emulator")
        calls = self.watch_popen()
        finding, err = self.run_spawn()
        self.assertEqual(finding.rule_id, "offscope-session.spawn-unavailable")
        self.assertIn("'claude' is not installed", finding.message)
        self.assertIn("is not installed", err)
        self.assertEqual(calls, [])

    def test_an_unwritable_state_directory_fails_open_and_says_so(self):
        blocked = os.path.join(self.state.name, "not-a-directory")
        with open(blocked, "w", encoding="utf-8") as handle:
            handle.write("this is a file, so no handoff folder can be made inside it\n")
        os.environ[spawn.STATE_ENV] = blocked
        self.autospawn()
        self.stub("claude")
        self.stub("x-terminal-emulator")
        calls = self.watch_popen()
        finding, err = self.run_spawn()
        self.assertEqual(finding.rule_id, "offscope-session.spawn-unavailable")
        self.assertIn("the handoff could not be written", finding.message)
        self.assertIn("the handoff could not be written", err)
        self.assertEqual(calls, [])


class TestTerminalChain(SpawnCase):
    def test_headless_with_tmux_present_selects_tmux(self):
        self.autospawn()
        self.stub("claude")
        self.stub("x-terminal-emulator")
        tmux = self.stub("tmux")
        calls = self.watch_popen()
        finding, _ = self.run_spawn()
        self.assertEqual(finding.rule_id, "offscope-session.spawn-started")
        self.assertIn("tmux", finding.message)
        argv = calls[0]["argv"]
        self.assertEqual(argv[0], tmux)
        self.assertEqual(argv[1:3], ["new-session", "-d"])
        self.assertEqual(argv[3:5], ["-c", self.repo.name])

    def test_a_display_does_not_select_tmux_over_a_window_terminal(self):
        os.environ["DISPLAY"] = ":0"
        self.autospawn()
        self.stub("claude")
        terminal = self.stub("x-terminal-emulator")
        self.stub("tmux")
        calls = self.watch_popen()
        finding, _ = self.run_spawn()
        self.assertEqual(finding.rule_id, "offscope-session.spawn-started")
        self.assertEqual(calls[0]["argv"][0], terminal)

    def test_the_terminal_override_wins_over_the_rest_of_the_chain(self):
        self.autospawn()
        self.stub("claude")
        self.stub("x-terminal-emulator")
        mine = self.stub("my-terminal")
        os.environ[spawn.TERMINAL_ENV] = "my-terminal"
        calls = self.watch_popen()
        finding, _ = self.run_spawn()
        self.assertEqual(finding.rule_id, "offscope-session.spawn-started")
        self.assertEqual(calls[0]["argv"][0], mine)

    def test_the_chain_is_tried_in_order_when_earlier_terminals_are_absent(self):
        os.environ["DISPLAY"] = ":0"
        names = [name for name, _ in spawn.terminal_candidates("/tmp/s.sh", "/tmp")]
        self.assertEqual(names, ["x-terminal-emulator", "gnome-terminal", "konsole", "xterm"])
        self.autospawn()
        self.stub("claude")
        konsole = self.stub("konsole")
        calls = self.watch_popen()
        finding, _ = self.run_spawn()
        self.assertEqual(finding.rule_id, "offscope-session.spawn-started")
        self.assertEqual(calls[0]["argv"][0], konsole)

    def test_macos_opens_the_script_with_open_and_never_osascript(self):
        self.autospawn()
        self.stub("claude")
        opener = self.stub("open")
        self.stub("osascript")
        calls = self.watch_popen()
        with patch.object(platform, "system", lambda: "Darwin"):
            finding, _ = self.run_spawn()
        self.assertEqual(finding.rule_id, "offscope-session.spawn-started")
        argv = calls[0]["argv"]
        self.assertEqual(argv[0], opener)
        self.assertEqual(argv[1:3], ["-a", "Terminal"])
        self.assertEqual(argv[3], os.path.join(self.state.name, "scripts", "handoff1.sh"))
        self.assertNotIn("osascript", " ".join(argv))


class TestFailsOpen(SpawnCase):
    def test_garbage_input_never_raises_and_never_reports_started(self):
        for verdict in ({}, None, "not a dict", {"id": None}, {"answer": "not a dict"}):
            with self.subTest(verdict=verdict), redirect_stderr(io.StringIO()):
                findings = spawn.spawn(verdict, None)
                self.assertEqual(len(findings), 1)
                self.assertEqual(findings[0].rule_id, "offscope-session.spawn-unavailable")

    def test_a_terminal_that_cannot_be_started_fails_open(self):
        self.autospawn()
        self.stub("claude")
        self.stub("x-terminal-emulator")

        def boom(argv, **kwargs):
            raise OSError("no file descriptors left")

        with patch.object(subprocess, "Popen", boom):
            finding, err = self.run_spawn()
        self.assertEqual(finding.rule_id, "offscope-session.spawn-unavailable")
        self.assertIn("starting the terminal failed: OSError", finding.message)
        self.assertIn("no file descriptors left", err)


if __name__ == "__main__":
    unittest.main()
