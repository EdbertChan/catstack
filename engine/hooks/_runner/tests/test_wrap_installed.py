from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RUNNER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNNER_DIR))

import wrap_installed


class _Fixtures:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.old_home = os.environ.get("HOME")
        os.environ["HOME"] = str(self.home)
        self.addCleanup(self._restore_home)
        self.claude_path = self.home / ".claude" / "settings.json"
        self.cursor_path = self.home / ".cursor" / "hooks.json"
        self.codex_path = self.home / ".codex" / "hooks.json"
        self._write_json(self.claude_path, self._claude_fixture())
        self._write_json(self.cursor_path, self._cursor_fixture())
        self._write_json(self.codex_path, self._codex_fixture())

    def _restore_home(self):
        if self.old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.old_home

    def _write_json(self, path: Path, data: object):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")

    def _read_json(self, path: Path) -> object:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)

    def _run(self) -> tuple[int, str]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = wrap_installed.main()
        return code, output.getvalue()

    def _claude_fixture(self) -> dict:
        return {
            "model": "sonnet",
            "hooks": {
                "Stop": [
                    {
                        "matcher": "Bash",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "python3 $HOME/.claude/hooks/diu-stop/claude_stop_check.py",
                                "timeout": 30,
                                "keep": "yes",
                            },
                            {
                                "type": "command",
                                "command": "python3 $HOME/bin/foreign_hook.py",
                                "timeout": 7,
                            },
                        ],
                    }
                ],
                "UserPromptSubmit": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "python3 $HOME/.claude/hooks/cat-mode-default/claude_prompt_submit.py --mode gentle",
                            }
                        ]
                    }
                ],
            },
        }

    def _cursor_fixture(self) -> dict:
        return {
            "version": 1,
            "hooks": {
                "preToolUse": [
                    {
                        "matcher": "*",
                        "command": "python3 $HOME/.cursor/hooks/scope-lock/cursor_pretool_scope.py",
                        "timeout": 5,
                    }
                ],
                "stop": [
                    {
                        "type": "prompt",
                        "prompt": "Find the assistant response.",
                        "timeout": 30,
                    }
                ],
            },
        }

    def _codex_fixture(self) -> dict:
        return {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "python3 $HOME/.codex/hooks/pr-schema-gate/claude_pretooluse.py",
                                "timeout": 5,
                            }
                        ],
                    }
                ]
            }
        }


class WrapInstalled(_Fixtures, unittest.TestCase):
    def test_match_direct(self):
        self.assertEqual(
            wrap_installed.match_direct("python3 $HOME/.claude/hooks/diu-stop/claude_stop_check.py --x"),
            ("claude", "diu-stop", "claude_stop_check.py", " --x"),
        )
        self.assertIsNone(
            wrap_installed.match_direct("python3 $HOME/.claude/hooks/_runner/run.py --timeout 5 x/y.py")
        )

    def test_wraps_all_harnesses_and_is_idempotent(self):
        claude_before = self._read_json(self.claude_path)
        cursor_before = self._read_json(self.cursor_path)
        code, output = self._run()
        self.assertEqual(code, 0, output)
        self.assertIn(f"wrapped 2 entr(ies) in {self.claude_path}", output)
        self.assertIn(f"wrapped 1 entr(ies) in {self.cursor_path}", output)
        self.assertIn(f"wrapped 1 entr(ies) in {self.codex_path}", output)

        claude = self._read_json(self.claude_path)
        cursor = self._read_json(self.cursor_path)
        codex = self._read_json(self.codex_path)

        claude_stop = claude["hooks"]["Stop"][0]["hooks"]
        self.assertEqual(
            claude_stop[0]["command"],
            f"{sys.executable} $HOME/.claude/hooks/_runner/run.py --timeout 29.5 diu-stop/claude_stop_check.py",
        )
        self.assertEqual(claude_stop[0]["keep"], "yes")
        self.assertEqual(claude_stop[1], claude_before["hooks"]["Stop"][0]["hooks"][1])
        self.assertEqual(
            claude["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"],
            f"{sys.executable} $HOME/.claude/hooks/_runner/run.py --timeout 59.5 "
            "cat-mode-default/claude_prompt_submit.py --mode gentle",
        )
        self.assertEqual(
            cursor["hooks"]["preToolUse"][0]["command"],
            f"{sys.executable} $HOME/.cursor/hooks/_runner/run.py --timeout 4.5 scope-lock/cursor_pretool_scope.py",
        )
        self.assertEqual(cursor["hooks"]["stop"][0], cursor_before["hooks"]["stop"][0])
        self.assertEqual(
            codex["hooks"]["PreToolUse"][0]["hooks"][0]["command"],
            f"{sys.executable} $HOME/.codex/hooks/_runner/run.py --timeout 4.5 pr-schema-gate/claude_pretooluse.py",
        )

        first_bytes = {
            path: path.read_bytes()
            for path in (self.claude_path, self.cursor_path, self.codex_path)
        }
        code, output = self._run()
        self.assertEqual(code, 0, output)
        self.assertIn(f"already up to date: {self.claude_path}", output)
        self.assertEqual(first_bytes[self.claude_path], self.claude_path.read_bytes())
        self.assertEqual(first_bytes[self.cursor_path], self.cursor_path.read_bytes())
        self.assertEqual(first_bytes[self.codex_path], self.codex_path.read_bytes())

    def test_direct_duplicate_of_wrapped_hook_collapses_to_one_entry(self):
        code, output = self._run()
        self.assertEqual(code, 0, output)
        cursor = self._read_json(self.cursor_path)
        cursor["hooks"]["preToolUse"].append(
            {
                "matcher": "*",
                "command": "python3 $HOME/.cursor/hooks/scope-lock/cursor_pretool_scope.py",
                "timeout": 5,
            }
        )
        self._write_json(self.cursor_path, cursor)

        code, output = self._run()
        self.assertEqual(code, 0, output)
        cursor = self._read_json(self.cursor_path)
        matches = [
            entry
            for entry in cursor["hooks"]["preToolUse"]
            if "scope-lock/cursor_pretool_scope.py" in entry.get("command", "")
        ]
        self.assertEqual(len(matches), 1, matches)

    def _use_fake_python_dir(self, *, minor: int | None, name: str = "fake-pythons") -> str:
        python_dir = self.home / name
        python_dir.mkdir(exist_ok=True)
        env_patch = mock.patch.dict(
            os.environ, {"CATSTACK_HOOK_PYTHON_DIRS": str(python_dir)}
        )
        env_patch.start()
        self.addCleanup(env_patch.stop)
        os.environ.pop("CATSTACK_HOOK_PYTHON", None)
        version_patch = mock.patch("wrap_installed.sys.version_info", (3, 9, 0))
        version_patch.start()
        self.addCleanup(version_patch.stop)
        if minor is None:
            return ""
        python_path = python_dir / f"python3.{minor}"
        python_path.touch()
        python_path.chmod(0o755)
        return str(python_path)

    def test_direct_wrap_uses_absolute_interpreter_path_for_every_harness(self):
        python = self._use_fake_python_dir(minor=13)
        code, output = self._run()
        self.assertEqual(code, 0, output)
        claude = self._read_json(self.claude_path)
        cursor = self._read_json(self.cursor_path)
        codex = self._read_json(self.codex_path)
        self.assertEqual(
            claude["hooks"]["Stop"][0]["hooks"][0]["command"],
            f"{python} $HOME/.claude/hooks/_runner/run.py --timeout 29.5 diu-stop/claude_stop_check.py",
        )
        self.assertEqual(
            cursor["hooks"]["preToolUse"][0]["command"],
            f"{python} $HOME/.cursor/hooks/_runner/run.py --timeout 4.5 scope-lock/cursor_pretool_scope.py",
        )
        self.assertEqual(
            codex["hooks"]["PreToolUse"][0]["hooks"][0]["command"],
            f"{python} $HOME/.codex/hooks/_runner/run.py --timeout 4.5 pr-schema-gate/claude_pretooluse.py",
        )

    def test_rewrap_is_idempotent_and_upgrades_bare_python3_prefix(self):
        python = self._use_fake_python_dir(minor=13)
        claude = self._read_json(self.claude_path)
        claude["hooks"]["Stop"][0]["hooks"][0]["command"] = (
            f"{python} $HOME/.claude/hooks/_runner/run.py --timeout 29.5 diu-stop/claude_stop_check.py"
        )
        claude["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"] = (
            "python3 $HOME/.claude/hooks/_runner/run.py --timeout 59.5 "
            "cat-mode-default/claude_prompt_submit.py --mode gentle"
        )
        self._write_json(self.claude_path, claude)

        code, output = self._run()
        self.assertEqual(code, 0, output)
        updated = self._read_json(self.claude_path)
        self.assertEqual(
            updated["hooks"]["Stop"][0]["hooks"][0]["command"],
            f"{python} $HOME/.claude/hooks/_runner/run.py --timeout 29.5 diu-stop/claude_stop_check.py",
        )
        self.assertEqual(
            updated["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"],
            f"{python} $HOME/.claude/hooks/_runner/run.py --timeout 59.5 "
            "cat-mode-default/claude_prompt_submit.py --mode gentle",
        )

        before = self.claude_path.read_bytes()
        code, output = self._run()
        self.assertEqual(code, 0, output)
        self.assertIn(f"already up to date: {self.claude_path}", output)
        self.assertEqual(self.claude_path.read_bytes(), before)

    def test_no_interpreter_available_keeps_bare_python3_and_warns(self):
        python_dir_str = self._use_fake_python_dir(minor=None, name="empty-pythons")
        output = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(err):
            code = wrap_installed.main()
        self.assertEqual(code, 0, output.getvalue())
        self.assertIn(python_dir_str, err.getvalue())

        claude = self._read_json(self.claude_path)
        self.assertEqual(
            claude["hooks"]["Stop"][0]["hooks"][0]["command"],
            "python3 $HOME/.claude/hooks/_runner/run.py --timeout 29.5 diu-stop/claude_stop_check.py",
        )

    def test_malformed_json_is_unchecked_and_exits_two(self):
        self.claude_path.write_text("{not-json", encoding="utf-8")
        code, output = self._run()
        self.assertEqual(code, 2)
        self.assertIn(f"unchecked: {self.claude_path}:", output)
        self.assertIn(f"wrapped 1 entr(ies) in {self.cursor_path}", output)


    def _touch(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    def _notify_fixture(self) -> tuple[Path, list[object]]:
        hooks = self.home / ".codex" / "hooks"
        self._touch(hooks / "wrong-check-reflect" / "codex_notify.py")
        self._touch(hooks / "llm-judge" / "codex_notify.py")
        self._touch(hooks / "diu-stop" / "codex_notify.py")
        nested = json.dumps(["python3", str(hooks / "diu-stop" / "codex_notify.py")])
        argv = [
            "python3", str(hooks / "wrong-check-reflect" / "codex_notify.py"),
            "python3", str(hooks / "llm-judge" / "codex_notify.py"),
            "/Applications/Other.app/client", "turn-ended", "--previous-notify", nested,
        ]
        path = self.home / ".codex" / "config.toml"
        path.write_text('model = "x"\nnotify = ' + json.dumps(argv) + '\n\n[features]\nhooks = true\n', encoding="utf-8")
        return path, argv

    def test_codex_notify_scripts_are_wrapped_once_and_the_rest_is_untouched(self):
        path, argv = self._notify_fixture()
        runner = str(self.home / ".codex" / "hooks" / "_runner" / "run.py")
        code, output = self._run()
        self.assertEqual(code, 0)
        self.assertIn(f"wrapped 3 notify entr(ies) in {path}", output)
        self.assertIn(f"unwrapped: {path}: notify chain nested in another program's argument: diu-stop/codex_notify.py", output)
        text = path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith('model = "x"\nnotify = '))
        self.assertTrue(text.endswith('\n\n[features]\nhooks = true\n'))
        _text, _match, wrapped = wrap_installed.read_notify(path)
        self.assertEqual(
            wrapped,
            [
                "python3", runner, "--notify", "--timeout", "59.5", "wrong-check-reflect/codex_notify.py",
                "python3", runner, "--notify", "--timeout", "59.5", "llm-judge/codex_notify.py",
                "python3", runner, "--notify", "--timeout", "59.5", "diu-stop/codex_notify.py",
                *argv[4:6],
            ],
        )
        code, output = self._run()
        self.assertIn(f"already up to date: {path}", output)
        self.assertEqual(path.read_text(encoding="utf-8"), text)

    def test_nested_catstack_entry_with_missing_script_is_dropped(self):
        hooks = self.home / ".codex" / "hooks"
        self._touch(hooks / "llm-judge" / "codex_notify.py")
        missing_diu_stop = hooks / "diu-stop" / "codex_notify.py"
        nested = json.dumps(["python3", str(missing_diu_stop), "python3", str(hooks / "llm-judge" / "codex_notify.py")])
        argv = ["/Applications/Other.app/client", "turn-ended", "--previous-notify", nested]
        path = self.home / ".codex" / "config.toml"
        path.write_text("notify = " + json.dumps(argv) + "\n", encoding="utf-8")

        code, output = self._run()
        self.assertEqual(code, 0, output)
        self.assertIn(f"wrapped 1 notify entr(ies) in {path}", output)
        self.assertIn(
            f"unwrapped: {path}: dropped diu-stop/codex_notify.py: {missing_diu_stop} does not exist", output
        )
        _text, _match, wrapped = wrap_installed.read_notify(path)
        self.assertNotIn(str(missing_diu_stop), json.dumps(wrapped))
        self.assertIn("llm-judge/codex_notify.py", json.dumps(wrapped))
        self.assertIn("/Applications/Other.app/client", wrapped)
        self.assertNotIn("--previous-notify", wrapped)

    def _six_layer_notify_fixture(self) -> tuple[Path, str, str]:
        hooks = self.home / ".codex" / "hooks"
        diu_canonical = hooks / "diu-stop" / "codex_notify.py"
        judge_canonical = hooks / "llm-judge" / "codex_notify.py"
        self._touch(diu_canonical)
        self._touch(judge_canonical)
        stale_diu_stop = self.home / "old-checkout" / "catstack" / "hooks" / "diu-stop" / "codex_notify.py"

        tail = [str(self.home / "Applications" / "Codex Computer Use.app" / "client"), "turn-ended"]
        chain: list[object] = ["python3", str(stale_diu_stop), "python3", str(judge_canonical), *tail]
        for _ in range(5):
            chain = [
                "python3", str(diu_canonical), "python3", str(judge_canonical),
                *tail, "--previous-notify", json.dumps(chain),
            ]
        path = self.home / ".codex" / "config.toml"
        text = 'model = "x"\nnotify = ' + json.dumps(chain) + '\n\n[features]\nhooks = true\n'
        path.write_text(text, encoding="utf-8")
        return path, str(diu_canonical), str(judge_canonical)

    def test_real_six_layer_notify_chain_flattens_to_one_catstack_layer(self):
        path, diu_canonical, judge_canonical = self._six_layer_notify_fixture()
        runner = str(self.home / ".codex" / "hooks" / "_runner" / "run.py")
        tail = [str(self.home / "Applications" / "Codex Computer Use.app" / "client"), "turn-ended"]

        code, output = self._run()
        self.assertEqual(code, 0, output)
        self.assertIn(f"wrapped 2 notify entr(ies) in {path}", output)

        _text, _match, wrapped = wrap_installed.read_notify(path)
        self.assertEqual(
            wrapped,
            [
                "python3", runner, "--notify", "--timeout", "59.5", "diu-stop/codex_notify.py",
                "python3", runner, "--notify", "--timeout", "59.5", "llm-judge/codex_notify.py",
                *tail,
            ],
        )
        serialized = json.dumps(wrapped)
        self.assertEqual(serialized.count("Codex Computer Use.app"), 1)
        self.assertEqual(serialized.count("diu-stop/codex_notify.py"), 1)
        self.assertNotIn("old-checkout", serialized)
        self.assertNotIn("--previous-notify", serialized)

        first_bytes = path.read_bytes()
        code, output = self._run()
        self.assertEqual(code, 0, output)
        self.assertIn(f"already up to date: {path}", output)
        self.assertEqual(path.read_bytes(), first_bytes)

    def test_malformed_notify_is_unchecked_and_exits_two(self):
        path = self.home / ".codex" / "config.toml"
        path.write_text("notify = [not json]\n", encoding="utf-8")
        code, output = self._run()
        self.assertEqual(code, 2)
        self.assertIn(f"unchecked: {path}: notify:", output)


class DispatcherFlag(_Fixtures, unittest.TestCase):
    def setUp(self):
        super().setUp()
        env_patch = mock.patch.dict(os.environ, {"CATSTACK_HOOK_DISPATCHER": "1"})
        env_patch.start()
        self.addCleanup(env_patch.stop)

    def test_flag_off_is_byte_identical_to_todays_wrap(self):
        os.environ["CATSTACK_HOOK_DISPATCHER"] = "0"
        code, output = self._run()
        self.assertEqual(code, 0, output)
        claude = self._read_json(self.claude_path)
        stop_hooks = claude["hooks"]["Stop"][0]["hooks"]
        self.assertEqual(
            stop_hooks[0]["command"],
            f"{sys.executable} $HOME/.claude/hooks/_runner/run.py --timeout 29.5 diu-stop/claude_stop_check.py",
        )
        self.assertEqual(stop_hooks[1], self._claude_fixture()["hooks"]["Stop"][0]["hooks"][1])
        self.assertNotIn("collapsed", output)

    def test_claude_collapses_every_matcher_group_into_one_dispatcher_entry_per_event(self):
        code, output = self._run()
        self.assertEqual(code, 0, output)
        self.assertIn("collapsed 2 into per-event dispatcher entries", output)
        claude = self._read_json(self.claude_path)

        stop_groups = claude["hooks"]["Stop"]
        self.assertEqual(len(stop_groups), 2)
        foreign_group, dispatcher_group = stop_groups
        self.assertEqual(foreign_group["hooks"], [self._claude_fixture()["hooks"]["Stop"][0]["hooks"][1]])
        self.assertEqual(dispatcher_group["matcher"], "*")
        self.assertEqual(len(dispatcher_group["hooks"]), 1)
        self.assertEqual(
            dispatcher_group["hooks"][0]["command"],
            f"{sys.executable} $HOME/.claude/hooks/_runner/dispatch.py --event Stop --timeout 29.5",
        )
        self.assertEqual(dispatcher_group["hooks"][0]["timeout"], 30)

        prompt_groups = claude["hooks"]["UserPromptSubmit"]
        self.assertEqual(len(prompt_groups), 1)
        self.assertNotIn("matcher", prompt_groups[0])
        self.assertEqual(
            prompt_groups[0]["hooks"][0]["command"],
            f"{sys.executable} $HOME/.claude/hooks/_runner/dispatch.py --event UserPromptSubmit --timeout 59.5",
        )

    def test_cursor_collapses_flat_entries_and_leaves_non_command_entries_alone(self):
        code, output = self._run()
        self.assertEqual(code, 0, output)
        cursor = self._read_json(self.cursor_path)
        pretool = cursor["hooks"]["preToolUse"]
        self.assertEqual(len(pretool), 1)
        self.assertEqual(pretool[0]["matcher"], "*")
        self.assertEqual(
            pretool[0]["command"],
            f"{sys.executable} $HOME/.cursor/hooks/_runner/dispatch.py --event preToolUse --timeout 4.5",
        )
        self.assertEqual(cursor["hooks"]["stop"], self._cursor_fixture()["hooks"]["stop"])

    def test_codex_collapses_nested_entries(self):
        code, output = self._run()
        self.assertEqual(code, 0, output)
        codex = self._read_json(self.codex_path)
        pretool = codex["hooks"]["PreToolUse"]
        self.assertEqual(len(pretool), 1)
        self.assertEqual(
            pretool[0]["hooks"][0]["command"],
            f"{sys.executable} $HOME/.codex/hooks/_runner/dispatch.py --event PreToolUse --timeout 4.5",
        )

    def test_collapsing_is_idempotent(self):
        code, output = self._run()
        self.assertEqual(code, 0, output)
        first = {
            path: path.read_bytes() for path in (self.claude_path, self.cursor_path, self.codex_path)
        }
        code, output = self._run()
        self.assertEqual(code, 0, output)
        self.assertIn(f"already up to date: {self.claude_path}", output)
        for path, before in first.items():
            self.assertEqual(path.read_bytes(), before)

    def test_a_second_foreign_command_sharing_the_dispatched_event_survives(self):
        cursor = self._read_json(self.cursor_path)
        cursor["hooks"]["preToolUse"].append(
            {"matcher": "Bash", "command": "python3 $HOME/bin/other_pretool.py", "timeout": 10}
        )
        self._write_json(self.cursor_path, cursor)
        code, output = self._run()
        self.assertEqual(code, 0, output)
        cursor = self._read_json(self.cursor_path)
        commands = [entry["command"] for entry in cursor["hooks"]["preToolUse"]]
        self.assertIn("python3 $HOME/bin/other_pretool.py", commands)
        self.assertEqual(
            sum(1 for c in commands if "_runner/dispatch.py" in c),
            1,
        )


class NotifyChainOwnershipTest(unittest.TestCase):
    """A --previous-notify argument belongs to the program in front of it; only
    catstack's own entries move, and only real catstack paths count as ours."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name
        self.addCleanup(self.tmp.cleanup)

    def _installed(self, hook):
        path = os.path.join(self.home, ".codex", "hooks", hook, "codex_notify.py")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w", encoding="utf-8").close()
        return path

    def test_a_foreign_programs_previous_notify_stays_nested(self):
        argv = ["/Apps/Sky", "turn-ended", "--previous-notify", '["/usr/local/bin/my-notifier","--sound"]']
        normalized, messages = wrap_installed.normalize_notify_argv(argv, self.home)
        self.assertEqual(normalized, argv)
        self.assertEqual(messages, [])

    def test_catstack_moves_out_of_a_foreign_level_and_the_foreign_rest_stays_nested(self):
        diu = self._installed("diu-stop")
        nested = json.dumps(["python3", diu, "/usr/local/bin/my-notifier", "--sound"])
        argv = ["/Apps/Sky", "turn-ended", "--previous-notify", nested]
        normalized, _messages = wrap_installed.normalize_notify_argv(argv, self.home)
        self.assertEqual(
            normalized,
            ["python3", diu, "/Apps/Sky", "turn-ended", "--previous-notify", '["/usr/local/bin/my-notifier", "--sound"]'],
        )

    def test_a_hooks_path_that_is_not_catstack_is_left_alone(self):
        argv = ["python3", "/opt/tool/hooks/notify/run.py", "--flag"]
        normalized, messages = wrap_installed.normalize_notify_argv(argv, self.home)
        self.assertEqual(normalized, argv)
        self.assertEqual(messages, [])

    def test_a_shipped_hook_name_outside_codex_hooks_is_still_catstack(self):
        diu = self._installed("diu-stop")
        stale = os.path.join(self.home, "old-checkout", "hooks", "diu-stop", "codex_notify.py")
        normalized, _messages = wrap_installed.normalize_notify_argv(["python3", stale, "/other"], self.home)
        self.assertEqual(normalized, ["python3", diu, "/other"])

    def test_a_dead_top_level_catstack_entry_is_dropped_like_a_nested_one(self):
        missing = os.path.join(self.home, ".codex", "hooks", "diu-stop", "codex_notify.py")
        normalized, messages = wrap_installed.normalize_notify_argv(["python3", missing, "/other"], self.home)
        self.assertEqual(normalized, ["/other"])
        self.assertIn(f"dropped diu-stop/codex_notify.py: {missing} does not exist", messages)


if __name__ == "__main__":
    unittest.main()
