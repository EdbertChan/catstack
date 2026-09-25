#!/usr/bin/env python3
from __future__ import annotations

from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HOOK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOOK_DIR))

import codex_prompt_submit  # noqa: E402
import detect as hook_detect  # noqa: E402


@contextmanager
def hook_env(**updates: str):
    old = os.environ.copy()
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["CATSTACK_HOOK_METRICS_DIR"] = tmp
        os.environ.update(updates)
        try:
            yield Path(tmp)
        finally:
            os.environ.clear()
            os.environ.update(old)


def event_rows(directory: Path) -> list[dict[str, object]]:
    today = datetime.now(timezone.utc).date().isoformat()
    path = directory / f"events-{today}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def write_settings(path: Path, command: str) -> None:
    path.write_text(
        json.dumps({
            "hooks": {
                "UserPromptSubmit": [
                    {"matcher": "*", "hooks": [{"type": "command", "command": command}]}
                ]
            }
        }),
        encoding="utf-8",
    )


def deleted_hook_payload(root: Path, session_id: str) -> tuple[dict[str, object], Path]:
    repo = root / "catstack"
    (repo / ".git").mkdir(parents=True)
    (repo / "engine" / "hooks").mkdir(parents=True)
    installed = root / "installed" / "hooks" / "split-scope"
    installed.mkdir(parents=True)
    script = installed / "claude_prompt_submit.py"
    script.write_text("# still installed\n", encoding="utf-8")
    settings = root / "settings.json"
    write_settings(settings, f"python3 {script}")
    return (
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": session_id,
            "transcript_path": str(root / f"{session_id}.jsonl"),
            "settings_path": str(settings),
        },
        repo,
    )


def run_codex(payload: dict[str, object]) -> tuple[str, str]:
    stderr = StringIO()
    stdout = StringIO()
    with patch.object(sys, "stdin", StringIO(json.dumps(payload))):
        with redirect_stdout(stdout), redirect_stderr(stderr):
            codex_prompt_submit.main()
    return stdout.getvalue(), stderr.getvalue()


class HookFreshnessSdkModeTest(unittest.TestCase):
    def test_warn_override_changes_deleted_installed_hook_stop_to_warning(self) -> None:
        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name)
            stop_payload, repo = deleted_hook_payload(root / "stop", "hook-freshness-stop")
            warn_payload, _repo = deleted_hook_payload(root / "warn", "hook-freshness-warn")
            with patch.object(hook_detect, "STATE_DIR", str(root / "state")):
                with hook_env(CATSTACK_HOOKS_REPO=str(repo)):
                    stop_out, stop_err = run_codex(stop_payload)
                with hook_env(
                    CATSTACK_HOOKS_REPO=str(repo),
                    CATSTACK_HOOK_MODE_HOOK_FRESHNESS="warn",
                ):
                    warn_out, warn_err = run_codex(warn_payload)

        stop_body = json.loads(stop_out)
        warn_body = json.loads(warn_out)
        self.assertEqual("", stop_err)
        self.assertEqual("block", stop_body["decision"])
        self.assertIn("split-scope", stop_body["reason"])
        self.assertEqual("", warn_err)
        self.assertNotIn("decision", warn_body)
        self.assertIn("split-scope", warn_body["hookSpecificOutput"]["additionalContext"])

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name)
            payload, repo = deleted_hook_payload(root, "hook-freshness-event-row")
            with patch.object(hook_detect, "STATE_DIR", str(root / "state")):
                with hook_env(CATSTACK_HOOKS_REPO=str(repo)) as metrics:
                    out, err = run_codex(payload)
                    rows = event_rows(metrics)

        finding_rows = [row for row in rows if row["rule_id"]]
        self.assertEqual("", err)
        self.assertIn("split-scope", out)
        self.assertEqual(1, len(finding_rows))
        self.assertEqual("hook-freshness.deleted-installed-hook", finding_rows[0]["rule_id"])
        self.assertEqual("hook-freshness", finding_rows[0]["hook"])
        self.assertEqual("stop", finding_rows[0]["mode"])
        self.assertEqual("stopped", finding_rows[0]["action"])

    def test_behind_checkout_stays_warning(self) -> None:
        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name)
            repo = root / "catstack"
            repo.mkdir()
            subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
            (repo / "README.md").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)
            base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
            (repo / "README.md").write_text("origin\n", encoding="utf-8")
            subprocess.run(["git", "commit", "-am", "origin"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=repo, check=True)
            subprocess.run(["git", "reset", "--hard", base], cwd=repo, check=True, capture_output=True)
            hook_dir = repo / "engine" / "hooks" / "diu-stop"
            hook_dir.mkdir(parents=True)
            script = hook_dir / "claude_stop_check.py"
            script.write_text("# installed\n", encoding="utf-8")
            settings = root / "settings.json"
            write_settings(settings, f"python3 {script}")
            payload = {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "hook-freshness-behind",
                "transcript_path": str(root / "behind.jsonl"),
                "settings_path": str(settings),
            }

            with patch.object(hook_detect, "STATE_DIR", str(root / "state")):
                with hook_env(CATSTACK_HOOKS_REPO=str(repo)) as metrics:
                    out, err = run_codex(payload)
                    rows = event_rows(metrics)

        body = json.loads(out)
        finding_rows = [row for row in rows if row["rule_id"]]
        self.assertEqual("", err)
        self.assertNotIn("decision", body)
        self.assertIn("1 commit behind origin/main", body["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(["hook-freshness.stale-checkout"], [row["rule_id"] for row in finding_rows])
        self.assertEqual(["warn"], [row["mode"] for row in finding_rows])
        self.assertEqual(["warned"], [row["action"] for row in finding_rows])


if __name__ == "__main__":
    unittest.main()
