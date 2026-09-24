from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

RUNNER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNNER_DIR))

import wrap_installed


class WrapInstalled(unittest.TestCase):
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
            "python3 $HOME/.claude/hooks/_runner/run.py --timeout 29.5 diu-stop/claude_stop_check.py",
        )
        self.assertEqual(claude_stop[0]["keep"], "yes")
        self.assertEqual(claude_stop[1], claude_before["hooks"]["Stop"][0]["hooks"][1])
        self.assertEqual(
            claude["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"],
            "python3 $HOME/.claude/hooks/_runner/run.py --timeout 59.5 cat-mode-default/claude_prompt_submit.py --mode gentle",
        )
        self.assertEqual(
            cursor["hooks"]["preToolUse"][0]["command"],
            "python3 $HOME/.cursor/hooks/_runner/run.py --timeout 4.5 scope-lock/cursor_pretool_scope.py",
        )
        self.assertEqual(cursor["hooks"]["stop"][0], cursor_before["hooks"]["stop"][0])
        self.assertEqual(
            codex["hooks"]["PreToolUse"][0]["hooks"][0]["command"],
            "python3 $HOME/.codex/hooks/_runner/run.py --timeout 4.5 pr-schema-gate/claude_pretooluse.py",
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

    def test_malformed_json_is_unchecked_and_exits_two(self):
        self.claude_path.write_text("{not-json", encoding="utf-8")
        code, output = self._run()
        self.assertEqual(code, 2)
        self.assertIn(f"unchecked: {self.claude_path}:", output)
        self.assertIn(f"wrapped 1 entr(ies) in {self.cursor_path}", output)


    def _notify_fixture(self) -> tuple[Path, list[object]]:
        hooks = self.home / ".codex" / "hooks"
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
        self.assertIn(f"wrapped 2 notify entr(ies) in {path}", output)
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
                *argv[4:],
            ],
        )
        code, output = self._run()
        self.assertIn(f"already up to date: {path}", output)
        self.assertEqual(path.read_text(encoding="utf-8"), text)

    def test_malformed_notify_is_unchecked_and_exits_two(self):
        path = self.home / ".codex" / "config.toml"
        path.write_text("notify = [not json]\n", encoding="utf-8")
        code, output = self._run()
        self.assertEqual(code, 2)
        self.assertIn(f"unchecked: {path}: notify:", output)

if __name__ == "__main__":
    unittest.main()
