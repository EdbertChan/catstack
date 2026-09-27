from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SDK_DIR = os.path.join(os.path.dirname(RUNNER_DIR), "_sdk")
FLAGS_DIR = os.path.join(os.path.dirname(RUNNER_DIR), "_flags")
CHAOS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chaos")


class DispatchCLI(unittest.TestCase):
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

    def _write_subagent_stop_sdk_hook(self, name: str, fixture: str) -> None:
        sdk_target = os.path.join(self.hooks_root, "_sdk")
        if not os.path.exists(sdk_target):
            shutil.copytree(SDK_DIR, sdk_target)
            shutil.copytree(FLAGS_DIR, os.path.join(self.hooks_root, "_flags"))
        hook_dir = os.path.join(self.hooks_root, name)
        os.makedirs(hook_dir)
        shutil.copy2(os.path.join(CHAOS_DIR, fixture), os.path.join(hook_dir, "detect.py"))
        entry = {
            "hooks": [
                {
                    "type": "command",
                    "command": f"python3 $HOME/.claude/hooks/{name}/detect.py",
                }
            ]
        }
        manifest = {
            "dispatch": {"SubagentStop": True},
            "hooks": {"Stop": [entry]},
        }
        with open(os.path.join(hook_dir, "claude.hook.json"), "w", encoding="utf-8") as handle:
            json.dump(manifest, handle)

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["HOME"] = self.home
        env["CATSTACK_HOOK_METRICS_DIR"] = self.metrics_dir
        env["CATSTACK_HOOK_MODE_CHAOS_A_OK_ALPHA"] = "warn"
        env["CATSTACK_HOOK_MODE_CHAOS_Z_OK_OMEGA"] = "warn"
        return env

    def _stdin(self, tool_name: str | None = None, event: str = "PreToolUse") -> bytes:
        payload = {"hook_event_name": event, "session_id": "s1"}
        if tool_name is not None:
            payload["tool_name"] = tool_name
        if event == "SubagentStop":
            payload["chaos_label"] = "alpha"
        return json.dumps(payload).encode()

    def _run(
        self,
        event: str = "PreToolUse",
        timeout: str = "5",
        tool_name: str | None = None,
        detector_timeout: str | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        argv = [sys.executable, os.path.join(self.runner_dir, "dispatch.py"), "--event", event, "--timeout", timeout]
        if detector_timeout is not None:
            argv.extend(["--detector-timeout", detector_timeout])
        return subprocess.run(
            argv,
            input=self._stdin(tool_name, event),
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

    def test_subagent_stop_chaos_fixtures_isolate_three_failure_modes_and_keep_siblings(self):
        self._write_subagent_stop_sdk_hook("chaos-a-ok-alpha", "ok_hook.py")
        self._write_subagent_stop_sdk_hook("chaos-b-raise", "raise_hook.py")
        self._write_subagent_stop_sdk_hook("chaos-c-hang", "hang_hook.py")
        self._write_subagent_stop_sdk_hook("chaos-d-exit", "exit_hook.py")
        self._write_subagent_stop_sdk_hook("chaos-z-ok-omega", "ok_hook.py")

        result = self._run(event="SubagentStop", timeout="5", detector_timeout="1")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"chaos-a-ok-alpha", result.stdout)
        self.assertIn(b"chaos-z-ok-omega", result.stdout)
        rows = {row["hook"]: row for row in self._rows()}
        self.assertEqual(
            set(rows),
            {"chaos-a-ok-alpha", "chaos-b-raise", "chaos-c-hang", "chaos-d-exit", "chaos-z-ok-omega"},
        )
        self.assertEqual(rows["chaos-a-ok-alpha"]["outcome"], "spoke")
        self.assertEqual(rows["chaos-a-ok-alpha"]["rule_ids"], ["chaos.alpha"])
        self.assertGreaterEqual(rows["chaos-a-ok-alpha"]["duration_ms"], 0)
        self.assertEqual(rows["chaos-b-raise"]["outcome"], "crashed")
        self.assertEqual(rows["chaos-c-hang"]["outcome"], "timed_out")
        self.assertEqual(rows["chaos-d-exit"]["outcome"], "crashed")
        self.assertEqual(rows["chaos-d-exit"]["exit_code"], 3)
        self.assertEqual(rows["chaos-z-ok-omega"]["outcome"], "spoke")
        self.assertEqual(rows["chaos-z-ok-omega"]["rule_ids"], ["chaos.alpha"])
        self.assertIn(b"catstack-hook-error chaos-b-raise", result.stderr)
        self.assertIn(b"chaos-c-hang/detect.py timed out after 1", result.stderr)
        self.assertIn(b"chaos-d-exit/detect.py exited with code 3", result.stderr)

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
ROW_KEYS = ("harness", "hook", "script", "event", "event_uid", "outcome")


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

    def _install(self, harness: str, verdict: str, dispatcher: str) -> str:
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

    def _fire(self, harness: str, verdict: str, dispatcher: str):
        home = self._install(harness, verdict, dispatcher)
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


class SubagentStopPilot(unittest.TestCase):
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
        sdk_dir = os.path.join(os.path.dirname(RUNNER_DIR), "_sdk")
        shutil.copytree(sdk_dir, os.path.join(self.hooks_root, "_sdk"))
        shutil.copytree(FLAGS_DIR, os.path.join(self.hooks_root, "_flags"))

    def _hook(self, name: str, detect_body: str | None) -> None:
        hook_dir = os.path.join(self.hooks_root, name)
        os.makedirs(hook_dir)
        script = "claude_stop_check.py"
        script_path = os.path.join(hook_dir, script)
        if detect_body is None:
            with open(script_path, "w", encoding="utf-8") as handle:
                handle.write(
                    "import json\n"
                    "print(json.dumps({'hookSpecificOutput': "
                    f"{{'hookEventName': 'SubagentStop', 'additionalContext': '{name} fallback'}}}}))\n"
                )
        else:
            with open(script_path, "w", encoding="utf-8") as handle:
                handle.write("")
            with open(os.path.join(hook_dir, "detect.py"), "w", encoding="utf-8") as handle:
                handle.write(detect_body)
        manifest = {
            "hooks": {
                "Stop": [
                    {
                        "matcher": "*",
                        "hooks": [
                            {
                                "type": "command",
                                "command": f"python3 $HOME/.claude/hooks/{name}/{script}",
                                "timeout": 10,
                            }
                        ],
                    }
                ]
            },
            "dispatch": {"SubagentStop": True},
        }
        with open(os.path.join(hook_dir, "claude.hook.json"), "w", encoding="utf-8") as handle:
            json.dump(manifest, handle)

    def _run(self, payload: dict | None = None, *extra: str) -> subprocess.CompletedProcess[bytes]:
        env = os.environ.copy()
        env["HOME"] = self.home
        env["CATSTACK_HOOK_METRICS_DIR"] = self.metrics_dir
        for name in os.listdir(self.hooks_root):
            env[f"CATSTACK_HOOK_MODE_{name.upper().replace('-', '_')}"] = "warn"
        return subprocess.run(
            [
                sys.executable,
                os.path.join(self.runner_dir, "dispatch.py"),
                "--event",
                "SubagentStop",
                "--timeout",
                "3",
                "--detector-timeout",
                "0.25",
                *extra,
            ],
            input=json.dumps(payload or {"hook_event_name": "SubagentStop", "session_id": "s1"}).encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )

    def _rows(self) -> dict[str, dict]:
        with open(os.path.join(self.metrics_dir, "runs.jsonl"), encoding="utf-8") as handle:
            return {row["hook"]: row for row in map(json.loads, handle)}

    def test_sdk_hooks_run_in_process_and_missing_entrypoints_use_marked_fallback(self):
        self._hook(
            "fixture-sdk",
            "from finding import Finding\n"
            "def detect(event):\n"
            "    return [Finding('sdk.rule', 's', 'sdk spoke', 'e')]\n",
        )
        self._hook("fixture-fallback", None)

        result = self._run()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"sdk spoke", result.stdout)
        self.assertIn(b"fixture-fallback fallback", result.stdout)
        rows = self._rows()
        self.assertEqual(rows["fixture-sdk"]["dispatch_mode"], "in_process")
        self.assertEqual(rows["fixture-sdk"]["rule_ids"], ["sdk.rule"])
        self.assertEqual(rows["fixture-fallback"]["dispatch_mode"], "subprocess_fallback")

    def test_raise_and_hang_are_per_detector_and_do_not_drop_a_sibling(self):
        self._hook("fixture-crash", "def detect(event):\n    raise RuntimeError('boom')\n")
        self._hook("fixture-slow", "import time\ndef detect(event):\n    time.sleep(30)\n    return []\n")
        self._hook("fixture-nonzero", None)
        with open(
            os.path.join(self.hooks_root, "fixture-nonzero", "claude_stop_check.py"), "w", encoding="utf-8"
        ) as handle:
            handle.write("raise SystemExit(7)\n")
        self._hook(
            "fixture-ok",
            "from finding import Finding\n"
            "def detect(event):\n"
            "    return [Finding('ok.rule', 's', 'sibling spoke', 'e')]\n",
        )

        result = self._run()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"sibling spoke", result.stdout)
        rows = self._rows()
        self.assertEqual(rows["fixture-crash"]["outcome"], "crashed")
        self.assertEqual(rows["fixture-slow"]["outcome"], "timed_out")
        self.assertEqual(rows["fixture-nonzero"]["outcome"], "crashed")
        self.assertEqual(rows["fixture-nonzero"]["dispatch_mode"], "subprocess_fallback")
        self.assertEqual(rows["fixture-ok"]["outcome"], "spoke")

    def test_transcript_is_parsed_once_and_shared_after_the_source_is_removed(self):
        transcript = os.path.join(self.tmp.name, "transcript.jsonl")
        with open(transcript, "w", encoding="utf-8") as handle:
            handle.write('{"type":"user","message":"one"}\n')
            handle.write('{"type":"assistant","message":"two"}\n')
        self._hook(
            "cache-a",
            "import json\nimport os\nfrom finding import Finding\n"
            "def detect(event):\n"
            "    with open(event['transcript_path'], encoding='utf-8') as handle:\n"
            "        rows = [json.loads(line.strip()) for line in handle if line.strip()]\n"
            "    os.unlink(event['transcript_path'])\n"
            "    return [Finding('cache.a', 's', f'a saw {len(rows)}', 'e')]\n",
        )
        self._hook(
            "cache-b",
            "import json\nfrom finding import Finding\n"
            "def detect(event):\n"
            "    with open(event['transcript_path'], encoding='utf-8') as handle:\n"
            "        rows = [json.loads(line.strip()) for line in handle if line.strip()]\n"
            "    return [Finding('cache.b', 's', f'b saw {len(rows)}', 'e')]\n",
        )

        result = self._run({"hook_event_name": "SubagentStop", "session_id": "s1", "transcript_path": transcript})

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"a saw 2", result.stdout)
        self.assertIn(b"b saw 2", result.stdout)

    def test_only_mode_exposes_one_detectors_pre_merge_verdict_for_replay(self):
        self._hook(
            "fixture-sdk",
            "from finding import Finding\n"
            "def detect(event):\n"
            "    return [Finding('sdk.rule', 's', 'exact context', 'e')]\n",
        )

        result = self._run(None, "--only", "fixture-sdk")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {"hookSpecificOutput": {"hookEventName": "SubagentStop", "additionalContext": "exact context"}},
        )
        self.assertEqual(self._rows()["fixture-sdk"]["dispatch_mode"], "in_process")


def rows_outcome(rows: list[dict[str, object]], hook: str) -> str:
    matches = [row["outcome"] for row in rows if row["hook"] == hook]
    assert len(matches) == 1, matches
    return matches[0]


if __name__ == "__main__":
    unittest.main()
