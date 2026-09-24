#!/usr/bin/env python3
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

HOOK_DIR = Path(__file__).resolve().parents[1]
SDK_DIR = HOOK_DIR.parent / "_sdk"
sys.path.insert(0, str(HOOK_DIR))
sys.path.insert(0, str(SDK_DIR))

import detect  # noqa: E402
import runtime  # noqa: E402


def fake_git(branch="main", behind="0"):
    def run(args, _cwd, _timeout=None):
        if args[0] == "branch":
            return branch
        if args[0] == "rev-list":
            return behind
        return ""
    return run


class HookFreshnessSdkModeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "catstack"
        (self.repo / ".git").mkdir(parents=True)
        (self.repo / "engine" / "hooks" / "diu-stop").mkdir(parents=True)
        self.settings_path = self.root / "settings.json"
        self.metrics_dir = self.root / "metrics"
        self.state_dir = self.root / "state"

    def test_mode_override_turns_deleted_installed_hook_stop_into_warning(self) -> None:
        self._write_settings(["python3 /live/hooks/deleted-hook/claude_prompt_submit.py"])
        event = self._event()
        env = {"CATSTACK_HOOK_MODE_HOOK_FRESHNESS": "warn"}

        caught, stdout, stderr = self._run(event, env=env)

        self.assertEqual(0, caught.exception.code)
        self.assertEqual("", stderr)
        body = json.loads(stdout)
        self.assertIn("additionalContext", body["hookSpecificOutput"])
        self.assertIn("no longer exists", body["hookSpecificOutput"]["additionalContext"])
        rows = self._rows()
        self.assertEqual(["hook-freshness.deleted-installed-hook"], [row["rule_id"] for row in rows])
        self.assertEqual("warned", rows[0]["action"])
        self.assertEqual("override", rows[0]["mode_source"])

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        self._write_settings([
            "python3 /live/hooks/deleted-hook/claude_prompt_submit.py",
            "python3 /live/hooks/diu-stop/claude_stop_check.py",
        ])
        event = self._event(branch="feature/hooks", behind="2")

        caught, _stdout, _stderr = self._run(event)

        self.assertEqual(0, caught.exception.code)
        rows = self._rows()
        self.assertEqual(
            [
                "hook-freshness.deleted-installed-hook",
                "hook-freshness.stale-checkout",
            ],
            [row["rule_id"] for row in rows],
        )
        self.assertEqual(["stopped", "warned"], [row["action"] for row in rows])

    def test_deleted_installed_hook_stops_but_behind_checkout_only_warns(self) -> None:
        self._write_settings(["python3 /live/hooks/deleted-hook/claude_prompt_submit.py"])
        deleted_event = self._event()

        deleted_caught, deleted_stdout, _deleted_stderr = self._run(deleted_event, harness="codex")

        self.assertEqual(0, deleted_caught.exception.code)
        self.assertEqual("block", json.loads(deleted_stdout)["decision"])
        self.assertEqual("stopped", self._rows()[0]["action"])

        self.metrics_dir.mkdir(exist_ok=True)
        for path in self.metrics_dir.glob("events-*.jsonl"):
            path.unlink()
        self._write_settings(["python3 /live/hooks/diu-stop/claude_stop_check.py"])
        behind_event = self._event(branch="feature/hooks", behind="2")

        behind_caught, behind_stdout, behind_stderr = self._run(behind_event, harness="codex")

        self.assertEqual(0, behind_caught.exception.code)
        self.assertEqual("", behind_stderr)
        body = json.loads(behind_stdout)
        self.assertNotIn("decision", body)
        self.assertIn("additionalContext", body["hookSpecificOutput"])
        rows = self._rows()
        self.assertEqual(["hook-freshness.stale-checkout"], [row["rule_id"] for row in rows])
        self.assertEqual(["warned"], [row["action"] for row in rows])

    def _write_settings(self, commands: list[str]) -> None:
        self.settings_path.write_text(
            json.dumps({
                "hooks": {
                    "UserPromptSubmit": [
                        {
                            "hooks": [
                                {"type": "command", "command": command}
                                for command in commands
                            ]
                        }
                    ]
                }
            }),
            encoding="utf-8",
        )

    def _event(self, branch: str = "main", behind: str = "0") -> dict[str, object]:
        return {
            "hook_event_name": "UserPromptSubmit",
            "session_id": f"session-{branch}-{behind}",
            "transcript_path": str(self.root / f"{branch}-{behind}.jsonl"),
            "hook_freshness_env": {"CATSTACK_HOOKS_REPO": str(self.repo)},
            "hook_freshness_settings_path": str(self.settings_path),
            "hook_freshness_branch": branch,
            "hook_freshness_behind": behind,
        }

    def _run(self, event: dict[str, object], harness: str = "claude", env: dict[str, str] | None = None):
        def detector(payload: dict[str, object]):
            return detect.detect(
                payload,
                run=fake_git(
                    branch=str(payload["hook_freshness_branch"]),
                    behind=str(payload["hook_freshness_behind"]),
                ),
                exists=lambda path: "deleted-hook" not in path,
            )

        with mock.patch.dict(
            os.environ,
            {"CATSTACK_HOOK_METRICS_DIR": str(self.metrics_dir), **(env or {})},
            clear=False,
        ), mock.patch.object(detect, "STATE_DIR", str(self.state_dir)), self._stdio(json.dumps(event)):
            with self.assertRaises(SystemExit) as caught:
                runtime.run_hook("hook-freshness", harness, detector, "UserPromptSubmit")
            stdout = sys.stdout.getvalue()
            stderr = sys.stderr.getvalue()
        return caught, stdout, stderr

    def _rows(self) -> list[dict[str, object]]:
        files = list(self.metrics_dir.glob("events-*.jsonl"))
        self.assertEqual(1, len(files))
        return [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]

    @contextlib.contextmanager
    def _stdio(self, stdin_text: str):
        old_stdin = sys.stdin
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdin = io.StringIO(stdin_text)
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            yield
        finally:
            sys.stdin = old_stdin
            sys.stdout = old_stdout
            sys.stderr = old_stderr


if __name__ == "__main__":
    unittest.main()
