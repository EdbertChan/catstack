#!/usr/bin/env python3
from __future__ import annotations

from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from io import StringIO
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

HOOK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOOK_DIR))

import codex_prompt_submit  # noqa: E402


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


def write_registry(path: Path, mode: str) -> None:
    path.write_text(
        f"""
[hooks.hook-health]
mode = "{mode}"
why_mode = "habit"
summary = "Notes hooks that crashed."

[thresholds]
min_closed_findings = 30
promote_max_ignore_rate = 0.02
demote_min_ignore_rate = 0.10
review_min_ignore_rate = 0.50
review_min_unchecked_rate = 0.05
followup_window_checks = 3
""".lstrip(),
        encoding="utf-8",
    )


def write_notice(metrics: Path, session_id: str) -> None:
    folder = metrics / "hook-health-notices" / f"codex-{session_id}"
    folder.mkdir(parents=True)
    (folder / "1.txt").write_text(
        "hook-health: 1 hook run(s) failed since the last prompt: "
        "demo/x.py crashed (exit 1): boom -- run python3 ~/.claude/hooks/_runner/report.py for the table.\n",
        encoding="utf-8",
    )


def event_rows(directory: Path) -> list[dict[str, object]]:
    today = datetime.now(timezone.utc).date().isoformat()
    path = directory / f"events-{today}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def run_codex(payload: dict[str, object]) -> tuple[str, str]:
    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        old_stdin = sys.stdin
        sys.stdin = StringIO(json.dumps(payload))
        try:
            try:
                try:
                    codex_prompt_submit.main()
                except TypeError as exc:
                    if "harness" not in str(exc):
                        raise
                    codex_prompt_submit.main("codex")
            except SystemExit as exc:
                if exc.code not in (0, None):
                    raise
        finally:
            sys.stdin = old_stdin
    return stdout.getvalue(), stderr.getvalue()


class HookHealthSdkModeTest(unittest.TestCase):
    def test_warn_override_changes_stop_registry_response_to_warning(self) -> None:
        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name)
            registry = root / "hooks.toml"
            write_registry(registry, "stop")
            with hook_env() as metrics:
                write_notice(metrics, "hook-health-stop")
                stop_out, stop_err = run_codex(
                    {
                        "hook_event_name": "UserPromptSubmit",
                        "session_id": "hook-health-stop",
                        "registry_path": str(registry),
                    }
                )
            with hook_env(CATSTACK_HOOK_MODE_HOOK_HEALTH="warn") as metrics:
                write_notice(metrics, "hook-health-warn")
                warn_out, warn_err = run_codex(
                    {
                        "hook_event_name": "UserPromptSubmit",
                        "session_id": "hook-health-warn",
                        "registry_path": str(registry),
                    }
                )

        stop_body = json.loads(stop_out)
        warn_body = json.loads(warn_out)
        self.assertEqual("", stop_err)
        self.assertEqual("block", stop_body["decision"])
        self.assertIn("demo/x.py crashed", stop_body["reason"])
        self.assertEqual("", warn_err)
        self.assertNotIn("decision", warn_body)
        self.assertIn("demo/x.py crashed", warn_body["hookSpecificOutput"]["additionalContext"])

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        with hook_env() as metrics:
            write_notice(metrics, "hook-health-event-row")
            out, err = run_codex(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "hook-health-event-row",
                }
            )
            rows = event_rows(metrics)

        finding_rows = [row for row in rows if row["rule_id"]]
        self.assertEqual("", err)
        self.assertIn("demo/x.py crashed", out)
        self.assertEqual(1, len(finding_rows))
        self.assertEqual("hook-health.failed-runs", finding_rows[0]["rule_id"])
        self.assertEqual("hook-health", finding_rows[0]["hook"])
        self.assertEqual("warn", finding_rows[0]["mode"])
        self.assertEqual("warned", finding_rows[0]["action"])


if __name__ == "__main__":
    unittest.main()
