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
from unittest.mock import patch


HOOK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOOK_DIR))

import claude_posttooluse  # noqa: E402
import claude_prompt_submit  # noqa: E402
import state  # noqa: E402


BULK_RENAME = "rename this config key across 40 files, and update every call site that reads the old name."


def run_main(main, payload: dict[str, object]) -> tuple[int, str, str]:
    stdout = StringIO()
    stderr = StringIO()
    with patch.object(sys, "stdin", StringIO(json.dumps(payload))):
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                main()
            except SystemExit as exc:
                return int(exc.code or 0), stdout.getvalue(), stderr.getvalue()
    return 0, stdout.getvalue(), stderr.getvalue()


@contextmanager
def hook_env(mode: str):
    with tempfile.TemporaryDirectory() as metrics, tempfile.TemporaryDirectory() as hook_state:
        with patch.object(state, "STATE_DIR", hook_state):
            with patch.dict(
                os.environ,
                {
                    "CATSTACK_HOOK_METRICS_DIR": metrics,
                    "CATSTACK_HOOK_MODE_BUILD_THE_LEVER": mode,
                },
                clear=False,
            ):
                yield Path(metrics)


def event_rows(directory: Path) -> list[dict[str, object]]:
    today = datetime.now(timezone.utc).date().isoformat()
    path = directory / f"events-{today}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def prompt_payload(session_id: str) -> dict[str, object]:
    return {
        "session_id": session_id,
        "hook_event_name": "UserPromptSubmit",
        "prompt": BULK_RENAME,
    }


def edit_payload(session_id: str, path: str) -> dict[str, object]:
    return {
        "session_id": session_id,
        "hook_event_name": "PostToolUse",
        "tool_name": "Write",
        "tool_input": {"path": path},
    }


class BuildTheLeverSdkModeTest(unittest.TestCase):
    def test_warn_override_changes_stop_response_to_warning(self) -> None:
        with hook_env("stop"):
            stop_code, stop_out, stop_err = run_main(
                claude_prompt_submit.main,
                prompt_payload("build-lever-stop"),
            )
        with hook_env("warn"):
            warn_code, warn_out, warn_err = run_main(
                claude_prompt_submit.main,
                prompt_payload("build-lever-warn"),
            )

        self.assertEqual(0, stop_code)
        self.assertEqual("", stop_err)
        self.assertEqual("block", json.loads(stop_out)["decision"])
        self.assertEqual(0, warn_code)
        self.assertEqual("", warn_err)
        warning = json.loads(warn_out)
        self.assertNotIn("decision", warning)
        self.assertIn(
            "build-the-lever",
            warning["hookSpecificOutput"]["additionalContext"],
        )

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        with hook_env("warn") as metrics:
            prompt_code, prompt_out, prompt_err = run_main(
                claude_prompt_submit.main,
                prompt_payload("build-lever-events-prompt"),
            )
            edit_results = [
                run_main(
                    claude_posttooluse.main,
                    edit_payload("build-lever-events-edits", path),
                )
                for path in ("a.ts", "b.ts", "c.ts", "d.ts")
            ]
            rows = event_rows(metrics)

        finding_rows = [row for row in rows if row["action"] == "warned"]
        self.assertEqual(0, prompt_code)
        self.assertEqual("", prompt_err)
        self.assertIn("build-the-lever", prompt_out)
        self.assertTrue(all(code == 0 and err == "" for code, _out, err in edit_results))
        self.assertIn("build-the-lever", edit_results[-1][1])
        self.assertEqual(
            ["build-the-lever.bulk-prompt", "build-the-lever.many-file-edits"],
            sorted(row["rule_id"] for row in finding_rows),
        )
        self.assertTrue(all(row["hook"] == "build-the-lever" for row in finding_rows))
        self.assertTrue(all(row["mode"] == "warn" for row in finding_rows))
        self.assertTrue(all(row["mode_source"] == "override" for row in finding_rows))


if __name__ == "__main__":
    unittest.main()
