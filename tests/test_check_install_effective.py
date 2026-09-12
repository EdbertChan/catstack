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
SCRIPT = REPO_ROOT / "scripts/check_install_effective.py"


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


if __name__ == "__main__":
    unittest.main()
