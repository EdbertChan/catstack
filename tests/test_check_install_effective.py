#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts/ci/check_install_effective.py"


def load_with_home(home: Path):
    previous = os.environ.get("HOME")
    os.environ["HOME"] = str(home)
    try:
        spec = importlib.util.spec_from_file_location("check_install_effective_under_test", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if previous is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = previous


def write_json(path: Path, data: object):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")


class TestCheckInstallEffectiveHookWrapping(unittest.TestCase):
    def test_reports_exactly_the_unwrapped_catstack_hook(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            write_json(
                home / ".claude/settings.json",
                {
                    "hooks": {
                        "Stop": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "python3 $HOME/.claude/hooks/diu-stop/claude_stop_check.py",
                                    },
                                    {
                                        "type": "command",
                                        "command": (
                                            "python3 $HOME/.claude/hooks/_runner/run.py --timeout 29.5 "
                                            "cat-mode-default/claude_prompt_submit.py"
                                        ),
                                    },
                                ]
                            }
                        ]
                    }
                },
            )
            module = load_with_home(home)
            problems, unchecked = module.check_hooks_wrapped()
        self.assertEqual(unchecked, [])
        self.assertEqual(
            problems,
            [
                "hook bypasses the metrics runner: "
                "python3 $HOME/.claude/hooks/diu-stop/claude_stop_check.py"
            ],
        )

    def test_malformed_hook_file_is_unchecked_not_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            path = home / ".claude/settings.json"
            path.parent.mkdir(parents=True)
            path.write_text("{not-json", encoding="utf-8")
            module = load_with_home(home)
            problems, unchecked = module.check_hooks_wrapped()
        self.assertEqual(problems, [])
        self.assertEqual(len(unchecked), 1)
        self.assertIn("unchecked", unchecked[0])
        self.assertIn(str(path), unchecked[0])

    def test_main_prints_bypass_in_installation_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            write_json(
                home / ".claude/settings.json",
                {
                    "hooks": {
                        "Stop": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "python3 $HOME/.claude/hooks/diu-stop/claude_stop_check.py",
                                    }
                                ]
                            }
                        ]
                    }
                },
            )
            module = load_with_home(home)
            module.sandbox_reason = lambda: None
            module.check_canary = lambda: ([], [])
            module.check_worktree_links = lambda: ([], [])
            module.check_links = lambda: []
            module.check_hooks_registered = lambda: []
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = module.main()
        self.assertEqual(code, 1)
        self.assertIn(
            "hook bypasses the metrics runner: "
            "python3 $HOME/.claude/hooks/diu-stop/claude_stop_check.py",
            output.getvalue(),
        )


def declared_hooks(module) -> dict[str, list[str]]:
    declared: dict[str, list[str]] = {}
    for hook_file in sorted((module.REPO / "engine/hooks").glob("*/claude*.hook.json")):
        data = json.loads(hook_file.read_text(encoding="utf-8"))
        for event, commands in module.hook_commands_by_event(data).items():
            declared.setdefault(event, []).extend(sorted(commands))
    return declared


def runner_wrapped(command: str) -> str:
    prefix = "python3 $HOME/.claude/hooks/"
    return f"python3 $HOME/.claude/hooks/_runner/run.py --timeout 9.5 {command[len(prefix):]}"


def settings_with(commands_by_event: dict[str, list[str]]) -> dict:
    return {
        "hooks": {
            event: [{"hooks": [{"type": "command", "command": c} for c in commands]}]
            for event, commands in commands_by_event.items()
        }
    }


class TestCheckHooksRegisteredThroughRunner(unittest.TestCase):
    def test_runner_wrapped_registration_counts_as_registered(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            module = load_with_home(home)
            declared = declared_hooks(module)
            self.assertTrue(declared)
            wrapped = {event: [runner_wrapped(c) for c in cmds] for event, cmds in declared.items()}
            write_json(home / ".claude/settings.json", settings_with(wrapped))
            self.assertEqual(module.check_hooks_registered(), [])

    def test_hook_missing_from_runner_wrapped_settings_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            module = load_with_home(home)
            declared = declared_hooks(module)
            event = sorted(declared)[0]
            dropped = declared[event][0]
            wrapped = {e: [runner_wrapped(c) for c in cmds if c != dropped] for e, cmds in declared.items()}
            write_json(home / ".claude/settings.json", settings_with(wrapped))
            problems = module.check_hooks_registered()
        self.assertEqual(len(problems), 1)
        self.assertIn(f"not registered for {event}", problems[0])
        self.assertTrue(problems[0].endswith(dropped))

    def test_same_script_under_another_event_does_not_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            module = load_with_home(home)
            declared = declared_hooks(module)
            event = sorted(declared)[0]
            moved = dict(declared)
            moved["NotAHookEvent"] = [declared[event][0]]
            moved[event] = declared[event][1:]
            wrapped = {e: [runner_wrapped(c) for c in cmds] for e, cmds in moved.items()}
            write_json(home / ".claude/settings.json", settings_with(wrapped))
            problems = module.check_hooks_registered()
        self.assertEqual(len(problems), 1)
        self.assertIn(f"not registered for {event}", problems[0])


if __name__ == "__main__":
    unittest.main()
