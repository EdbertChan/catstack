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
CATSTACK_ROOT = HOOK_DIR.parents[2]
sys.path.insert(0, str(HOOK_DIR))
sys.path.insert(0, str(CATSTACK_ROOT / "scripts"))

import claude_stop_autopr  # noqa: E402
import detect  # noqa: E402
from git_test_repo import init_repo  # noqa: E402


def git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def make_firing_repo(directory: str) -> Path:
    root = Path(directory) / "repo"
    root.mkdir()
    init_repo(str(root), "-b", "main")
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "Test")
    path = root / "engine" / "hooks" / "sample" / "detect.py"
    path.parent.mkdir(parents=True)
    path.write_text("pass\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    path.write_text("pass\nchanged = True\n", encoding="utf-8")
    return root


def run_claude(payload: dict[str, object]) -> tuple[int, str, str]:
    stdout = StringIO()
    stderr = StringIO()
    with patch.object(sys, "stdin", StringIO(json.dumps(payload))):
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                claude_stop_autopr.main()
            except SystemExit as exc:
                return int(exc.code or 0), stdout.getvalue(), stderr.getvalue()
    return 0, stdout.getvalue(), stderr.getvalue()


@contextmanager
def hook_env(**updates: str):
    old = os.environ.copy()
    os.environ.update(updates)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(old)


def event_rows(directory: Path) -> list[dict[str, object]]:
    today = datetime.now(timezone.utc).date().isoformat()
    path = directory / f"events-{today}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class AutoPrSdkModeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_tmp = tempfile.TemporaryDirectory()
        self.state_tmp = tempfile.TemporaryDirectory()
        self.metrics_tmp = tempfile.TemporaryDirectory()
        self.repo = make_firing_repo(self.repo_tmp.name)
        detect.STATE_DIR = self.state_tmp.name
        self.root_patch = patch.object(detect, "OWN_REPO_ROOT", str(self.repo.resolve()))
        self.root_patch.start()

    def tearDown(self) -> None:
        self.root_patch.stop()
        self.metrics_tmp.cleanup()
        self.state_tmp.cleanup()
        self.repo_tmp.cleanup()

    def payload(self, session_id: str) -> dict[str, object]:
        return {
            "cwd": str(self.repo),
            "hook_event_name": "Stop",
            "session_id": session_id,
        }

    def test_warn_override_changes_claude_stop_response_to_warning(self) -> None:
        with hook_env(
            CATSTACK_HOOK_METRICS_DIR=self.metrics_tmp.name,
            CATSTACK_HOOK_MODE_AUTO_PR="warn",
        ):
            first_code, first_out, first_err = run_claude(self.payload("auto-pr-warn"))
            code, stdout, stderr = run_claude(self.payload("auto-pr-warn"))

        self.assertEqual((0, "", ""), (first_code, first_out, first_err))
        self.assertEqual(0, code)
        self.assertEqual("", stderr)
        body = json.loads(stdout)
        output = body["hookSpecificOutput"]
        self.assertEqual("Stop", output["hookEventName"])
        self.assertIn("catstack changes detected", output["additionalContext"])

    def test_each_finding_writes_one_event_row_with_hook_rule_id(self) -> None:
        with hook_env(
            CATSTACK_HOOK_METRICS_DIR=self.metrics_tmp.name,
            CATSTACK_HOOK_MODE_AUTO_PR="warn",
        ):
            run_claude(self.payload("auto-pr-events"))
            code, stdout, stderr = run_claude(self.payload("auto-pr-events"))
            rows = event_rows(Path(self.metrics_tmp.name))

        finding_rows = [row for row in rows if row["action"] == "warned"]
        self.assertEqual(0, code)
        self.assertEqual("", stderr)
        self.assertIn("catstack changes detected", stdout)
        self.assertEqual(1, len(finding_rows))
        self.assertEqual("auto-pr.unpublished-changes", finding_rows[0]["rule_id"])
        self.assertEqual("auto-pr", finding_rows[0]["hook"])
        self.assertEqual("warn", finding_rows[0]["mode"])
        self.assertEqual("override", finding_rows[0]["mode_source"])


if __name__ == "__main__":
    unittest.main()
