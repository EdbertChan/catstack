#!/usr/bin/env python3
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
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

import claude_pretooluse_agent  # noqa: E402
import claude_prompt_submit  # noqa: E402
import detect  # noqa: E402
from test_hooks import Sandbox, REAL_PROMPT  # noqa: E402


def run_main(main, payload: dict[str, object], env: dict[str, str]) -> tuple[int, str, str]:
    stdout = StringIO()
    stderr = StringIO()
    with patch.object(sys, "stdin", StringIO(json.dumps(payload))):
        with patch.dict(os.environ, env, clear=True):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                try:
                    main()
                except SystemExit as exc:
                    return int(exc.code or 0), stdout.getvalue(), stderr.getvalue()
    return 0, stdout.getvalue(), stderr.getvalue()


def event_rows(directory: Path) -> list[dict[str, object]]:
    today = datetime.now(timezone.utc).date().isoformat()
    path = directory / f"events-{today}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class CatModeDefaultSdkModeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.box = Sandbox()
        self.metrics_tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.metrics_tmp.cleanup()
        self.box.cleanup()

    def env(self, **updates: str) -> dict[str, str]:
        env = self.box.environ({
            detect.FLAG: "1",
            "CATSTACK_HOOK_METRICS_DIR": self.metrics_tmp.name,
        })
        env.update(updates)
        return env

    def agent_payload(self, session_id: str) -> dict[str, object]:
        return {
            "hook_event_name": "PreToolUse",
            "session_id": session_id,
            "tool_name": "Agent",
            "cwd": self.box.cwd,
            "tool_input": {
                "description": "Apply a task",
                "prompt": "Investigate the failing test.",
            },
        }

    def test_warn_override_changes_stop_response_to_warning(self) -> None:
        stop_code, stop_out, stop_err = run_main(
            claude_pretooluse_agent.main,
            self.agent_payload("cat-mode-stop"),
            self.env(CATSTACK_HOOK_MODE_CAT_MODE_DEFAULT="stop"),
        )
        warn_code, warn_out, warn_err = run_main(
            claude_pretooluse_agent.main,
            self.agent_payload("cat-mode-warn"),
            self.env(CATSTACK_HOOK_MODE_CAT_MODE_DEFAULT="warn"),
        )

        self.assertEqual(2, stop_code)
        self.assertEqual("", stop_out)
        self.assertIn("cat-mode default is on", stop_err)
        self.assertEqual(0, warn_code)
        self.assertEqual("", warn_err)
        warning = json.loads(warn_out)
        output = warning["hookSpecificOutput"]
        self.assertEqual("PreToolUse", output["hookEventName"])
        self.assertIn("updatedInput", output)
        self.assertTrue(output["updatedInput"]["prompt"].startswith("cat-mode default is on: read and apply "))

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        payload = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "cat-mode-events",
            "prompt": REAL_PROMPT,
            "cwd": self.box.cwd,
        }
        code, out, err = run_main(
            claude_prompt_submit.main,
            payload,
            self.env(CATSTACK_HOOK_MODE_CAT_MODE_DEFAULT="warn"),
        )
        rows = event_rows(Path(self.metrics_tmp.name))

        finding_rows = [row for row in rows if row["rule_id"]]
        self.assertEqual(0, code)
        self.assertEqual("", err)
        self.assertIn("cat-mode default is on", out)
        self.assertEqual(1, len(finding_rows))
        self.assertEqual("cat-mode-default.prompt", finding_rows[0]["rule_id"])
        self.assertEqual("cat-mode-default", finding_rows[0]["hook"])
        self.assertEqual("warn", finding_rows[0]["mode"])
        self.assertEqual("override", finding_rows[0]["mode_source"])


if __name__ == "__main__":
    unittest.main()
