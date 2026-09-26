from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER_DIR)

from dispatch import INSTALLED_REGISTRY  # noqa: E402


class _DispatchFixture:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home")
        self.hooks_root = os.path.join(self.home, ".claude", "hooks")
        self.runner_dir = os.path.join(self.hooks_root, "_runner")
        self.metrics_dir = os.path.join(self.tmp.name, "metrics")
        os.makedirs(self.runner_dir)
        for name in ("run.py", "outcome.py", "dispatch.py"):
            shutil.copy2(os.path.join(RUNNER_DIR, name), os.path.join(self.runner_dir, name))

    def _write_hook(self, name: str, script: str, body: str, event: str = "PreToolUse", matcher=None) -> None:
        hook_dir = os.path.join(self.hooks_root, name)
        os.makedirs(hook_dir)
        with open(os.path.join(hook_dir, script), "w", encoding="utf-8") as handle:
            handle.write(body)
        entry = {"hooks": [{"type": "command", "command": f"python3 $HOME/.claude/hooks/{name}/{script}"}]}
        if matcher is not None:
            entry["matcher"] = matcher
        manifest = {"hooks": {event: [entry]}}
        with open(os.path.join(hook_dir, "claude.hook.json"), "w", encoding="utf-8") as handle:
            json.dump(manifest, handle)

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["HOME"] = self.home
        env["CATSTACK_HOOK_METRICS_DIR"] = self.metrics_dir
        return env

    def _stdin(self, tool_name: str | None = None) -> bytes:
        payload = {"hook_event_name": "PreToolUse", "session_id": "s1"}
        if tool_name is not None:
            payload["tool_name"] = tool_name
        return json.dumps(payload).encode()

    def _run(self, event: str = "PreToolUse", timeout: str = "5", tool_name: str | None = None) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [sys.executable, os.path.join(self.runner_dir, "dispatch.py"), "--event", event, "--timeout", timeout],
            input=self._stdin(tool_name),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._env(),
        )

    def _rows(self) -> list[dict[str, object]]:
        path = os.path.join(self.metrics_dir, "runs.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle]

    def _row_for(self, hook: str) -> dict[str, object]:
        matches = [row for row in self._rows() if row["hook"] == hook]
        self.assertEqual(len(matches), 1, matches)
        return matches[0]


class DispatchCLI(_DispatchFixture, unittest.TestCase):
    def test_a_raising_hook_gets_its_own_crashed_row_while_a_sibling_still_speaks(self):
        self._write_hook(
            "fixture-ok",
            "ok.py",
            "import json\nprint(json.dumps({'hookSpecificOutput': {'additionalContext': 'hi from ok'}}))\n",
        )
        self._write_hook("fixture-crash", "crash.py", "raise RuntimeError('boom')\n")

        result = self._run()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"hi from ok", result.stdout)
        ok_row = self._row_for("fixture-ok")
        self.assertEqual(ok_row["outcome"], "spoke")
        crash_row = self._row_for("fixture-crash")
        self.assertEqual(crash_row["outcome"], "crashed")
        self.assertNotEqual(crash_row["exit_code"], 0)

    def test_a_hanging_hook_gets_its_own_timed_out_row_while_a_sibling_still_speaks(self):
        self._write_hook(
            "fixture-ok",
            "ok.py",
            "import json\nprint(json.dumps({'hookSpecificOutput': {'additionalContext': 'hi from ok'}}))\n",
        )
        self._write_hook("fixture-slow", "slow.py", "import time\ntime.sleep(30)\n")

        result = self._run(timeout="1")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"hi from ok", result.stdout)
        ok_row = self._row_for("fixture-ok")
        self.assertEqual(ok_row["outcome"], "spoke")
        slow_row = self._row_for("fixture-slow")
        self.assertEqual(slow_row["outcome"], "timed_out")
        self.assertIn(b"fixture-slow/slow.py timed out after 1", result.stderr)

    def test_raising_and_hanging_siblings_each_get_their_own_row_in_the_same_dispatch(self):
        self._write_hook(
            "fixture-ok",
            "ok.py",
            "import json\nprint(json.dumps({'hookSpecificOutput': {'additionalContext': 'hi from ok'}}))\n",
        )
        self._write_hook("fixture-crash", "crash.py", "raise RuntimeError('boom')\n")
        self._write_hook("fixture-slow", "slow.py", "import time\ntime.sleep(30)\n")

        result = self._run(timeout="3")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"hi from ok", result.stdout)
        rows = {row["hook"]: row for row in self._rows()}
        self.assertEqual(set(rows), {"fixture-ok", "fixture-crash", "fixture-slow"})
        self.assertEqual(rows["fixture-ok"]["outcome"], "spoke")
        self.assertEqual(rows["fixture-crash"]["outcome"], "crashed")
        self.assertEqual(rows["fixture-slow"]["outcome"], "timed_out")

    def test_a_blocking_hook_wins_over_a_speaking_sibling(self):
        self._write_hook(
            "fixture-ok",
            "ok.py",
            "import json\nprint(json.dumps({'hookSpecificOutput': {'additionalContext': 'hi from ok'}}))\n",
        )
        self._write_hook(
            "fixture-block",
            "block.py",
            "import sys\nsys.stderr.write('nope\\n')\nsys.exit(2)\n",
        )

        result = self._run()

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"nope\n")
        self.assertEqual(rows_outcome(self._rows(), "fixture-block"), "blocked")

    def test_no_hooks_registered_for_the_event_is_a_quiet_success(self):
        self._write_hook("fixture-ok", "ok.py", "print('should not run')\n", event="Stop")

        result = self._run(event="PreToolUse")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(self._rows(), [])

    def test_matcher_on_the_manifest_filters_which_hooks_run(self):
        self._write_hook(
            "fixture-bash",
            "bash.py",
            "import json\nprint(json.dumps({'hookSpecificOutput': {'additionalContext': 'bash ran'}}))\n",
            matcher="Bash",
        )
        self._write_hook(
            "fixture-write",
            "write.py",
            "import json\nprint(json.dumps({'hookSpecificOutput': {'additionalContext': 'write ran'}}))\n",
            matcher="Write",
        )

        result = self._run(tool_name="Bash")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"bash ran", result.stdout)
        self.assertNotIn(b"write ran", result.stdout)
        self.assertEqual(rows_outcome(self._rows(), "fixture-bash"), "spoke")
        self.assertEqual(self._rows(), [row for row in self._rows() if row["hook"] == "fixture-bash"])


class DispatchKeepsTheRunAloneSkipAndCrashContract(_DispatchFixture, unittest.TestCase):
    BUDGET = "60"
    BLOCKING_STOP_HOOK = "import sys\nsys.stderr.write('the bug is y\\n')\nsys.exit(2)\n"
    CRASH_AFTER_SPEAKING = (
        "import json\n"
        "print(json.dumps({'decision': 'block', 'reason': 'half-written verdict'}))\n"
        "raise RuntimeError('boom')\n"
    )
    SPEAKING_HOOK = "import json\nprint(json.dumps({'hookSpecificOutput': {'additionalContext': 'hi from ok'}}))\n"

    def _dispatch(self, event: str, stdin: bytes, timeout: str | None = None) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [
                sys.executable,
                os.path.join(self.runner_dir, "dispatch.py"),
                "--event",
                event,
                "--timeout",
                timeout or self.BUDGET,
            ],
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._env(),
        )

    def _alone(self, hook_script: str, stdin: bytes, timeout: str | None = None) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [sys.executable, os.path.join(self.runner_dir, "run.py"), "--timeout", timeout or self.BUDGET, hook_script],
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._env(),
        )

    def _forget_rows(self) -> None:
        os.remove(os.path.join(self.metrics_dir, "runs.jsonl"))

    def _stop_stdin(self, reply: str) -> bytes:
        return json.dumps(
            {"hook_event_name": "Stop", "session_id": "s1", "last_assistant_message": reply}
        ).encode()

    def test_a_machine_deliverable_reply_skips_a_stop_hook_the_way_running_alone_does(self):
        self._write_hook("fixture-judge", "stop.py", self.BLOCKING_STOP_HOOK, event="Stop")
        stdin = self._stop_stdin(json.dumps({"title": "Publish", "body": "The bug is that it failed."}))

        alone = self._alone("fixture-judge/stop.py", stdin)
        self.assertEqual((alone.returncode, alone.stdout, alone.stderr), (0, b"", b""))
        self.assertEqual(self._row_for("fixture-judge")["skipped"], "machine-deliverable")
        self._forget_rows()

        dispatched = self._dispatch("Stop", stdin)

        self.assertEqual((dispatched.returncode, dispatched.stdout, dispatched.stderr), (0, b"", b""))
        row = self._row_for("fixture-judge")
        self.assertEqual(row["skipped"], "machine-deliverable")
        self.assertEqual(row["outcome"], "silent")
        self.assertEqual(row["exit_code"], 0)

    def test_a_prose_reply_still_reaches_the_stop_hook_through_dispatch(self):
        self._write_hook("fixture-judge", "stop.py", self.BLOCKING_STOP_HOOK, event="Stop")

        dispatched = self._dispatch("Stop", self._stop_stdin("The bug is that it failed."))

        self.assertEqual(dispatched.returncode, 2, dispatched.stderr)
        self.assertEqual(dispatched.stderr, b"the bug is y\n")
        self.assertNotIn("skipped", self._row_for("fixture-judge"))

    def test_a_crashing_hook_says_nothing_through_dispatch_the_way_it_says_nothing_alone(self):
        self._write_hook("fixture-crash", "crash.py", self.CRASH_AFTER_SPEAKING)

        alone = self._alone("fixture-crash/crash.py", self._stdin())
        self.assertEqual((alone.returncode, alone.stdout, alone.stderr), (0, b"", b""))
        self._forget_rows()

        dispatched = self._run(timeout=self.BUDGET)

        self.assertEqual((dispatched.returncode, dispatched.stdout, dispatched.stderr), (0, b"", b""))
        row = self._row_for("fixture-crash")
        self.assertEqual(row["outcome"], "crashed")
        self.assertNotEqual(row["exit_code"], 0)

    def test_a_crashing_sibling_is_hidden_while_a_speaking_sibling_still_speaks(self):
        self._write_hook("fixture-ok", "ok.py", self.SPEAKING_HOOK)
        self._write_hook("fixture-crash", "crash.py", self.CRASH_AFTER_SPEAKING)

        dispatched = self._run(timeout=self.BUDGET)

        self.assertEqual(dispatched.returncode, 0, dispatched.stderr)
        self.assertEqual(
            dispatched.stdout,
            json.dumps({"continue": True, "additionalContext": "[fixture-ok] hi from ok"}).encode(),
        )
        self.assertEqual(dispatched.stderr, b"")
        self.assertEqual(self._row_for("fixture-crash")["outcome"], "crashed")

    def test_a_crashing_hook_health_still_reaches_the_harness_through_dispatch(self):
        self._write_hook("hook-health", "crash.py", self.CRASH_AFTER_SPEAKING)

        dispatched = self._run(timeout=self.BUDGET)

        self.assertEqual(dispatched.returncode, 0, dispatched.stderr)
        self.assertIn(b"RuntimeError: boom", dispatched.stderr)
        self.assertIn(b"half-written verdict", dispatched.stdout)

    def test_a_crash_whose_row_could_not_be_written_is_not_hidden(self):
        self._write_hook("fixture-crash", "crash.py", self.CRASH_AFTER_SPEAKING)
        self.metrics_dir = os.path.join(self.tmp.name, "metrics-is-a-file")
        with open(self.metrics_dir, "w", encoding="utf-8") as handle:
            handle.write("")

        dispatched = self._run(timeout=self.BUDGET)

        self.assertEqual(dispatched.returncode, 0, dispatched.stderr)
        self.assertIn(b"RuntimeError: boom", dispatched.stderr)
        self.assertIn(b"catstack-hook-metrics: could not write row", dispatched.stderr)

    def test_a_hook_whose_script_is_gone_is_reported_not_hidden(self):
        self._write_hook("fixture-gone", "gone.py", "print('never runs')\n")
        os.remove(os.path.join(self.hooks_root, "fixture-gone", "gone.py"))

        dispatched = self._run(timeout=self.BUDGET)

        self.assertEqual(dispatched.returncode, 0, dispatched.stderr)
        self.assertIn(b"no such hook script", dispatched.stderr)
        self.assertEqual(self._row_for("fixture-gone")["outcome"], "crashed")


FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
FIXTURE_HOOK = "fixture-extra-manifest"
FIXTURE_SCRIPT = "speak.py"
FIXTURE_MESSAGE = "fixture hook spoke"
EXTRA_MANIFEST = {
    "claude": "claude.prompt.hook.json",
    "cursor": "cursor.prompt.hook.json",
    "codex": "codex.prompt.hook.json",
}
ALONE_SPEAK_STDOUT = {
    "claude": {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": FIXTURE_MESSAGE}},
    "cursor": {"additional_context": FIXTURE_MESSAGE},
    "codex": {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": FIXTURE_MESSAGE}},
}
ALONE_BLOCK_STDOUT = {
    "claude": None,
    "cursor": {"continue": False, "permission": "deny", "user_message": FIXTURE_MESSAGE},
    "codex": {
        "decision": "block",
        "reason": FIXTURE_MESSAGE,
        "hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": FIXTURE_MESSAGE},
    },
}
ALONE_BLOCK_EXIT = {"claude": 2, "cursor": 0, "codex": 0}
ROW_KEYS = ("harness", "hook", "script", "event", "outcome")


class HooksDeclaredInAnExtraManifest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _install(self, harness: str, verdict: str) -> tuple[str, str]:
        home = os.path.join(self.tmp.name, harness, "home")
        hooks_root = os.path.join(home, f".{harness}", "hooks")
        runner_dir = os.path.join(hooks_root, "_runner")
        os.makedirs(runner_dir)
        for name in ("run.py", "outcome.py", "dispatch.py"):
            shutil.copy2(os.path.join(RUNNER_DIR, name), os.path.join(runner_dir, name))
        hook_dir = os.path.join(hooks_root, FIXTURE_HOOK)
        os.makedirs(hook_dir)
        shutil.copy2(os.path.join(FIXTURES_DIR, FIXTURE_SCRIPT), os.path.join(hook_dir, FIXTURE_SCRIPT))
        command = f"python3 $HOME/.{harness}/hooks/{FIXTURE_HOOK}/{FIXTURE_SCRIPT} {harness} {verdict}"
        if harness == "cursor":
            entry: dict[str, object] = {"command": command, "timeout": 10}
        else:
            entry = {"hooks": [{"type": "command", "command": command, "timeout": 10}]}
        manifest_path = os.path.join(hook_dir, EXTRA_MANIFEST[harness])
        with open(manifest_path, "w", encoding="utf-8") as handle:
            json.dump({"hooks": {"UserPromptSubmit": [entry]}}, handle)
        return home, runner_dir

    def _invoke(self, home: str, runner_dir: str, label: str, argv: list[str]):
        metrics_dir = os.path.join(self.tmp.name, "metrics", label)
        env = os.environ.copy()
        env["HOME"] = home
        env["CATSTACK_HOOK_METRICS_DIR"] = metrics_dir
        result = subprocess.run(
            [sys.executable, *argv],
            input=json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "s1"}).encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        path = os.path.join(metrics_dir, "runs.jsonl")
        rows = []
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                rows = [json.loads(line) for line in handle]
        return result, rows

    def _both(self, harness: str, verdict: str):
        home, runner_dir = self._install(harness, verdict)
        alone, alone_rows = self._invoke(
            home,
            runner_dir,
            f"{harness}-{verdict}-alone",
            [
                os.path.join(runner_dir, "run.py"),
                "--timeout",
                "10",
                f"{FIXTURE_HOOK}/{FIXTURE_SCRIPT}",
                harness,
                verdict,
            ],
        )
        dispatched, dispatched_rows = self._invoke(
            home,
            runner_dir,
            f"{harness}-{verdict}-dispatched",
            [os.path.join(runner_dir, "dispatch.py"), "--event", "UserPromptSubmit", "--timeout", "10"],
        )
        return alone, alone_rows, dispatched, dispatched_rows

    def _only_row(self, rows: list[dict]) -> dict:
        self.assertEqual(len(rows), 1, rows)
        return rows[0]

    def test_a_speaking_hook_in_an_extra_manifest_reaches_dispatch_with_the_run_alone_contract(self):
        for harness in ("claude", "cursor", "codex"):
            with self.subTest(harness=harness):
                alone, alone_rows, dispatched, dispatched_rows = self._both(harness, "speak")
                expected_stderr = f"fixture-extra-manifest: {harness} speak\n".encode()

                self.assertEqual(alone.returncode, 0, alone.stderr)
                self.assertEqual(alone.stdout, json.dumps(ALONE_SPEAK_STDOUT[harness]).encode() + b"\n")
                self.assertEqual(alone.stderr, expected_stderr)

                self.assertEqual(dispatched.returncode, 0, dispatched.stderr)
                self.assertEqual(
                    dispatched.stdout,
                    json.dumps(
                        {"continue": True, "additionalContext": f"[{FIXTURE_HOOK}] {FIXTURE_MESSAGE}"}
                    ).encode(),
                )
                self.assertEqual(dispatched.stderr, expected_stderr)

                alone_row = self._only_row(alone_rows)
                dispatched_row = self._only_row(dispatched_rows)
                self.assertEqual(alone_row["outcome"], "spoke")
                self.assertEqual(
                    {key: dispatched_row[key] for key in ROW_KEYS},
                    {key: alone_row[key] for key in ROW_KEYS},
                )

    def test_a_blocking_hook_in_an_extra_manifest_reaches_dispatch_with_the_run_alone_verdict(self):
        for harness in ("claude", "cursor", "codex"):
            with self.subTest(harness=harness):
                alone, alone_rows, dispatched, dispatched_rows = self._both(harness, "block")
                expected_stderr = f"fixture-extra-manifest: {harness} block\n".encode()
                if harness == "claude":
                    expected_stderr += f"{FIXTURE_MESSAGE}\n".encode()
                    expected_alone_stdout = b""
                else:
                    expected_alone_stdout = json.dumps(ALONE_BLOCK_STDOUT[harness]).encode() + b"\n"

                self.assertEqual(alone.returncode, ALONE_BLOCK_EXIT[harness], alone.stderr)
                self.assertEqual(alone.stdout, expected_alone_stdout)
                self.assertEqual(alone.stderr, expected_stderr)

                self.assertEqual(dispatched.returncode, ALONE_BLOCK_EXIT[harness], dispatched.stderr)
                self.assertEqual(dispatched.stdout, expected_alone_stdout)
                self.assertEqual(dispatched.stderr, expected_stderr)

                alone_row = self._only_row(alone_rows)
                dispatched_row = self._only_row(dispatched_rows)
                self.assertEqual(alone_row["outcome"], "blocked")
                self.assertEqual(
                    {key: dispatched_row[key] for key in ROW_KEYS},
                    {key: alone_row[key] for key in ROW_KEYS},
                )


WRAP_INSTALLED = os.path.join(RUNNER_DIR, "wrap_installed.py")
INSTALLED_HOOK = "fixture-installed"
INSTALLED_CONFIG = {
    "claude": ".claude/settings.json",
    "cursor": ".cursor/hooks.json",
    "codex": ".codex/hooks.json",
}
INSTALLED_EVENT = {"claude": "UserPromptSubmit", "cursor": "beforeSubmitPrompt", "codex": "UserPromptSubmit"}


class HooksRegisteredTheWayInstallRegistersThem(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _install(self, harness: str, verdict: str, dispatcher: str, manifest: bool = True) -> str:
        home = os.path.join(self.tmp.name, f"{harness}-{verdict}-{dispatcher}", "home")
        hooks_root = os.path.join(home, f".{harness}", "hooks")
        runner_dir = os.path.join(hooks_root, "_runner")
        os.makedirs(runner_dir)
        for name in ("run.py", "outcome.py", "dispatch.py"):
            shutil.copy2(os.path.join(RUNNER_DIR, name), os.path.join(runner_dir, name))
        hook_dir = os.path.join(hooks_root, INSTALLED_HOOK)
        os.makedirs(hook_dir)
        shutil.copy2(os.path.join(FIXTURES_DIR, FIXTURE_SCRIPT), os.path.join(hook_dir, FIXTURE_SCRIPT))
        event = INSTALLED_EVENT[harness]
        command = f"python3 $HOME/.{harness}/hooks/{INSTALLED_HOOK}/{FIXTURE_SCRIPT} {harness} {verdict}"
        if harness == "cursor":
            config = {"version": 1, "hooks": {event: [{"command": command, "timeout": 10}]}}
        else:
            fragment = {"hooks": {event: [{"hooks": [{"type": "command", "command": command, "timeout": 10}]}]}}
            if manifest:
                with open(os.path.join(hook_dir, f"{harness}.hook.json"), "w", encoding="utf-8") as handle:
                    json.dump(fragment, handle)
            config = fragment
        config_path = os.path.join(home, INSTALLED_CONFIG[harness])
        with open(config_path, "w", encoding="utf-8") as handle:
            json.dump(config, handle)
        env = os.environ.copy()
        env["HOME"] = home
        env["CATSTACK_HOOK_DISPATCHER"] = dispatcher
        wrapped = subprocess.run(
            [sys.executable, WRAP_INSTALLED], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
        )
        self.assertEqual(wrapped.returncode, 0, wrapped.stdout + wrapped.stderr)
        return home

    def _installed_command(self, home: str, harness: str) -> str:
        with open(os.path.join(home, INSTALLED_CONFIG[harness]), encoding="utf-8") as handle:
            entries = json.load(handle)["hooks"][INSTALLED_EVENT[harness]]
        self.assertEqual(len(entries), 1, entries)
        entry = entries[0]
        hook = entry if harness == "cursor" else entry["hooks"][0]
        return hook["command"]

    def _fire(self, harness: str, verdict: str, dispatcher: str, manifest: bool = True):
        return self._fire_installed(self._install(harness, verdict, dispatcher, manifest), harness, dispatcher)

    def _fire_installed(self, home: str, harness: str, dispatcher: str):
        command = self._installed_command(home, harness)
        runner = "dispatch.py" if dispatcher == "1" else "run.py"
        self.assertIn(f"/_runner/{runner} ", command)
        metrics_dir = os.path.join(home, "metrics")
        env = os.environ.copy()
        env["HOME"] = home
        env["CATSTACK_HOOK_METRICS_DIR"] = metrics_dir
        result = subprocess.run(
            command,
            shell=True,
            input=json.dumps({"hook_event_name": INSTALLED_EVENT[harness], "session_id": "s1"}).encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        path = os.path.join(metrics_dir, "runs.jsonl")
        rows = []
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                rows = [json.loads(line) for line in handle]
        return result, rows

    def _only_row(self, rows: list[dict]) -> dict:
        self.assertEqual(len(rows), 1, rows)
        return rows[0]

    def test_a_speaking_installed_hook_reaches_dispatch_with_the_run_alone_contract(self):
        for harness in ("claude", "cursor", "codex"):
            with self.subTest(harness=harness):
                alone, alone_rows = self._fire(harness, "speak", "0")
                dispatched, dispatched_rows = self._fire(harness, "speak", "1")
                expected_stderr = f"fixture-extra-manifest: {harness} speak\n".encode()

                self.assertEqual(alone.returncode, 0, alone.stderr)
                self.assertEqual(alone.stdout, json.dumps(ALONE_SPEAK_STDOUT[harness]).encode() + b"\n")
                self.assertEqual(alone.stderr, expected_stderr)

                self.assertEqual(dispatched.returncode, 0, dispatched.stderr)
                self.assertEqual(
                    dispatched.stdout,
                    json.dumps(
                        {"continue": True, "additionalContext": f"[{INSTALLED_HOOK}] {FIXTURE_MESSAGE}"}
                    ).encode(),
                )
                self.assertEqual(dispatched.stderr, expected_stderr)

                alone_row = self._only_row(alone_rows)
                self.assertEqual(alone_row["outcome"], "spoke")
                self.assertEqual(
                    {key: self._only_row(dispatched_rows)[key] for key in ROW_KEYS},
                    {key: alone_row[key] for key in ROW_KEYS},
                )

    def test_a_blocking_installed_hook_reaches_dispatch_with_the_run_alone_verdict(self):
        for harness in ("claude", "cursor", "codex"):
            with self.subTest(harness=harness):
                alone, alone_rows = self._fire(harness, "block", "0")
                dispatched, dispatched_rows = self._fire(harness, "block", "1")
                expected_stderr = f"fixture-extra-manifest: {harness} block\n".encode()
                if harness == "claude":
                    expected_stderr += f"{FIXTURE_MESSAGE}\n".encode()
                    expected_alone_stdout = b""
                else:
                    expected_alone_stdout = json.dumps(ALONE_BLOCK_STDOUT[harness]).encode() + b"\n"

                self.assertEqual(alone.returncode, ALONE_BLOCK_EXIT[harness], alone.stderr)
                self.assertEqual(alone.stdout, expected_alone_stdout)
                self.assertEqual(alone.stderr, expected_stderr)

                self.assertEqual(dispatched.returncode, ALONE_BLOCK_EXIT[harness], dispatched.stderr)
                self.assertEqual(dispatched.stdout, expected_alone_stdout)
                self.assertEqual(dispatched.stderr, expected_stderr)

                alone_row = self._only_row(alone_rows)
                self.assertEqual(alone_row["outcome"], "blocked")
                self.assertEqual(
                    {key: self._only_row(dispatched_rows)[key] for key in ROW_KEYS},
                    {key: alone_row[key] for key in ROW_KEYS},
                )

    def test_a_codex_hook_wired_in_code_without_a_manifest_still_reaches_dispatch(self):
        registry = os.path.join(".codex", "hooks", INSTALLED_REGISTRY)
        off_home = self._install("codex", "speak", "0", manifest=False)
        self.assertFalse(os.path.exists(os.path.join(off_home, registry)), registry)
        alone, alone_rows = self._fire_installed(off_home, "codex", "0")

        on_home = self._install("codex", "speak", "1", manifest=False)
        self.assertTrue(os.path.exists(os.path.join(on_home, registry)), registry)
        dispatched, dispatched_rows = self._fire_installed(on_home, "codex", "1")

        self.assertEqual(alone.returncode, 0, alone.stderr)
        self.assertEqual(alone.stdout, json.dumps(ALONE_SPEAK_STDOUT["codex"]).encode() + b"\n")
        self.assertEqual(dispatched.returncode, 0, dispatched.stderr)
        self.assertEqual(
            dispatched.stdout,
            json.dumps({"continue": True, "additionalContext": f"[{INSTALLED_HOOK}] {FIXTURE_MESSAGE}"}).encode(),
        )
        self.assertEqual(
            {key: self._only_row(dispatched_rows)[key] for key in ROW_KEYS},
            {key: self._only_row(alone_rows)[key] for key in ROW_KEYS},
        )

    def test_rewrapping_an_already_collapsed_cursor_install_keeps_its_hooks(self):
        home = self._install("cursor", "speak", "1")
        env = os.environ.copy()
        env["HOME"] = home
        env["CATSTACK_HOOK_DISPATCHER"] = "1"
        again = subprocess.run([sys.executable, WRAP_INSTALLED], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        env["CATSTACK_HOOK_METRICS_DIR"] = os.path.join(home, "metrics")
        result = subprocess.run(
            self._installed_command(home, "cursor"),
            shell=True,
            input=json.dumps({"hook_event_name": "beforeSubmitPrompt", "session_id": "s1"}).encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"[{INSTALLED_HOOK}] {FIXTURE_MESSAGE}".encode(), result.stdout)

    def test_an_unreadable_cursor_registry_is_reported_not_read_as_no_hooks(self):
        home = self._install("cursor", "speak", "1")
        registry = os.path.join(home, ".cursor", "hooks", "_dispatch.json")
        with open(registry, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        env = os.environ.copy()
        env["HOME"] = home
        env["CATSTACK_HOOK_METRICS_DIR"] = os.path.join(home, "metrics")
        result = subprocess.run(
            self._installed_command(home, "cursor"),
            shell=True,
            input=json.dumps({"hook_event_name": "beforeSubmitPrompt", "session_id": "s1"}).encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"catstack-hook-dispatcher: could not read {registry}".encode(), result.stderr)


BLOCK_SCRIPT = "block.py"
BLOCK_EVENT = {"claude": "PreToolUse", "codex": "PreToolUse", "cursor": "preToolUse"}
BLOCK_FORMS = {"claude": ("exit2", "json"), "codex": ("exit2", "json"), "cursor": ("exit2", "json")}


class BlockReasonReachesTheHarness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _install(self, label: str, harness: str, hooks: list[tuple[str, str, str]]) -> tuple[str, str]:
        home = os.path.join(self.tmp.name, label, "home")
        hooks_root = os.path.join(home, f".{harness}", "hooks")
        runner_dir = os.path.join(hooks_root, "_runner")
        os.makedirs(runner_dir)
        for name in ("run.py", "outcome.py", "dispatch.py"):
            shutil.copy2(os.path.join(RUNNER_DIR, name), os.path.join(runner_dir, name))
        for hook, form, message in hooks:
            hook_dir = os.path.join(hooks_root, hook)
            os.makedirs(hook_dir)
            shutil.copy2(os.path.join(FIXTURES_DIR, BLOCK_SCRIPT), os.path.join(hook_dir, BLOCK_SCRIPT))
            command = f"python3 $HOME/.{harness}/hooks/{hook}/{BLOCK_SCRIPT} {harness} {form} {message}"
            if harness == "cursor":
                entry: dict[str, object] = {"command": command, "timeout": 10}
            else:
                entry = {"hooks": [{"type": "command", "command": command, "timeout": 10}]}
            with open(os.path.join(hook_dir, f"{harness}.hook.json"), "w", encoding="utf-8") as handle:
                json.dump({"hooks": {BLOCK_EVENT[harness]: [entry]}}, handle)
        return home, runner_dir

    def _invoke(self, home: str, label: str, harness: str, argv: list[str]):
        metrics_dir = os.path.join(self.tmp.name, "metrics", label)
        env = os.environ.copy()
        env["HOME"] = home
        env["CATSTACK_HOOK_METRICS_DIR"] = metrics_dir
        stdin = {"hook_event_name": BLOCK_EVENT[harness], "session_id": "s1", "tool_name": "Bash"}
        result = subprocess.run(
            [sys.executable, *argv],
            input=json.dumps(stdin).encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        path = os.path.join(metrics_dir, "runs.jsonl")
        rows = []
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                rows = [json.loads(line) for line in handle]
        return result, rows

    def _dispatch(self, home: str, runner_dir: str, label: str, harness: str):
        return self._invoke(
            home,
            f"{label}-dispatched",
            harness,
            [os.path.join(runner_dir, "dispatch.py"), "--event", BLOCK_EVENT[harness], "--timeout", "10"],
        )

    def test_a_lone_blocking_hook_dispatches_byte_identical_to_running_alone(self):
        for harness, forms in BLOCK_FORMS.items():
            for form in forms:
                with self.subTest(harness=harness, form=form):
                    label = f"{harness}-{form}"
                    home, runner_dir = self._install(label, harness, [("fixture-block", form, "no-rm-rf")])
                    alone, alone_rows = self._invoke(
                        home,
                        f"{label}-alone",
                        harness,
                        [
                            os.path.join(runner_dir, "run.py"),
                            "--timeout",
                            "10",
                            f"fixture-block/{BLOCK_SCRIPT}",
                            harness,
                            form,
                            "no-rm-rf",
                        ],
                    )
                    dispatched, dispatched_rows = self._dispatch(home, runner_dir, label, harness)

                    self.assertEqual(alone.returncode, 2 if form == "exit2" else 0, alone.stderr)
                    self.assertIn(b"no-rm-rf", alone.stderr if form == "exit2" else alone.stdout)
                    self.assertEqual(
                        (dispatched.returncode, dispatched.stdout, dispatched.stderr),
                        (alone.returncode, alone.stdout, alone.stderr),
                    )
                    self.assertEqual(len(alone_rows), 1, alone_rows)
                    self.assertEqual(len(dispatched_rows), 1, dispatched_rows)
                    self.assertEqual(alone_rows[0]["outcome"], "blocked")
                    self.assertEqual(
                        {key: dispatched_rows[0][key] for key in ROW_KEYS},
                        {key: alone_rows[0][key] for key in ROW_KEYS},
                    )

    def test_claude_json_block_keeps_its_reason_and_updated_input(self):
        home, runner_dir = self._install("claude-json-keep", "claude", [("fixture-block", "json", "no-rm-rf")])

        dispatched, _ = self._dispatch(home, runner_dir, "claude-json-keep", "claude")

        self.assertEqual(dispatched.returncode, 0, dispatched.stderr)
        hook_output = json.loads(dispatched.stdout)["hookSpecificOutput"]
        self.assertEqual(hook_output["permissionDecision"], "deny")
        self.assertEqual(hook_output["permissionDecisionReason"], "no-rm-rf")
        self.assertEqual(hook_output["updatedInput"], {"command": "echo safe"})

    def test_two_exit_two_blockers_put_both_reasons_on_stderr(self):
        for harness in BLOCK_FORMS:
            with self.subTest(harness=harness):
                label = f"{harness}-two-exit2"
                home, runner_dir = self._install(
                    label, harness, [("fixture-a", "exit2", "reason-a"), ("fixture-b", "exit2", "reason-b")]
                )

                dispatched, rows = self._dispatch(home, runner_dir, label, harness)

                self.assertEqual(dispatched.returncode, 2, dispatched.stderr)
                self.assertEqual(dispatched.stdout, b"")
                self.assertEqual(dispatched.stderr, b"reason-a\nreason-b\n")
                self.assertEqual([row["outcome"] for row in rows], ["blocked", "blocked"])

    def test_two_json_blockers_merge_into_one_json_block_in_the_harness_form(self):
        expected = {
            "claude": {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "reason-a\nreason-b",
                    "updatedInput": {"command": "echo safe"},
                }
            },
            "codex": {"decision": "block", "reason": "reason-a\nreason-b"},
            "cursor": {
                "continue": False,
                "permission": "deny",
                "user_message": "reason-a\nreason-b",
                "agent_message": "reason-a\nreason-b",
            },
        }
        for harness in BLOCK_FORMS:
            with self.subTest(harness=harness):
                label = f"{harness}-two-json"
                home, runner_dir = self._install(
                    label, harness, [("fixture-a", "json", "reason-a"), ("fixture-b", "json", "reason-b")]
                )

                dispatched, _ = self._dispatch(home, runner_dir, label, harness)

                self.assertEqual(dispatched.returncode, 0, dispatched.stderr)
                self.assertEqual(json.loads(dispatched.stdout), expected[harness])
                self.assertEqual(dispatched.stderr, b"")

    def test_an_exit_two_blocker_carries_a_json_blockers_reason_onto_stderr(self):
        for harness in BLOCK_FORMS:
            with self.subTest(harness=harness):
                label = f"{harness}-mixed"
                home, runner_dir = self._install(
                    label, harness, [("fixture-a", "json", "reason-a"), ("fixture-b", "exit2", "reason-b")]
                )

                dispatched, _ = self._dispatch(home, runner_dir, label, harness)

                self.assertEqual(dispatched.returncode, 2, dispatched.stderr)
                self.assertEqual(dispatched.stdout, b"")
                self.assertEqual(dispatched.stderr, b"reason-b\n[fixture-a] reason-a\n")


def rows_outcome(rows: list[dict[str, object]], hook: str) -> str:
    matches = [row["outcome"] for row in rows if row["hook"] == hook]
    assert len(matches) == 1, matches
    return matches[0]


if __name__ == "__main__":
    unittest.main()
