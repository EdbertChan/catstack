#!/usr/bin/env python3
"""SDK migration proof: registry mode drives the response, and every finding
writes one event row with the hook's rule_id.

Run: python3 -m unittest discover -s engine/hooks/cat-mode-default/tests -v
"""
from __future__ import annotations

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOKS_DIR)

import claude_pretooluse_agent  # noqa: E402
import claude_prompt_submit  # noqa: E402
from test_hooks import REAL_PROMPT, Sandbox  # noqa: E402

AGENT_TOOL_INPUT = {
    "description": "Reflect: hidden_stock sessions",
    "subagent_type": "general-purpose",
    "prompt": "Run reflect steps 1-4 over the last three hidden_stock sessions and report Accepted / Backlog / Rejected.",
}


def run_main(main, payload: dict, environ: dict, home: str) -> tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with patch.dict(os.environ, environ, clear=True):
            with patch.object(os.path, "expanduser", lambda p: p.replace("~", home, 1)):
                with redirect_stdout(out), redirect_stderr(err):
                    try:
                        main()
                    except SystemExit as exc:
                        return int(exc.code or 0), out.getvalue(), err.getvalue()
    return 0, out.getvalue(), err.getvalue()


class HooksSdkModeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.box = Sandbox()

    def tearDown(self) -> None:
        self.box.cleanup()

    def test_warn_override_changes_stop_response_to_warning(self) -> None:
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Agent",
            "cwd": self.box.cwd,
            "tool_input": dict(AGENT_TOOL_INPUT),
        }
        stop_code, stop_out, stop_err = run_main(
            claude_pretooluse_agent.main,
            payload,
            self.box.environ({"CATSTACK_CAT_MODE_DEFAULT": "1", "CATSTACK_HOOK_MODE_CAT_MODE_DEFAULT": "stop"}),
            self.box.home,
        )
        warn_code, warn_out, warn_err = run_main(
            claude_pretooluse_agent.main,
            payload,
            self.box.environ({"CATSTACK_CAT_MODE_DEFAULT": "1", "CATSTACK_HOOK_MODE_CAT_MODE_DEFAULT": "warn"}),
            self.box.home,
        )

        self.assertEqual(2, stop_code)
        self.assertEqual("", stop_out)
        self.assertIn("cat-mode default is on", stop_err)

        self.assertEqual(0, warn_code)
        self.assertEqual("", warn_err)
        updated = json.loads(warn_out)["hookSpecificOutput"]["updatedInput"]
        self.assertTrue(updated["prompt"].startswith("cat-mode default is on: read and apply "))
        self.assertTrue(updated["prompt"].endswith(AGENT_TOOL_INPUT["prompt"]))

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        prompt_environ = self.box.environ({"CATSTACK_CAT_MODE_DEFAULT": "1", "CATSTACK_HOOK_MODE_CAT_MODE_DEFAULT": "warn"})
        prompt_code, prompt_out, prompt_err = run_main(
            claude_prompt_submit.main,
            {"hook_event_name": "UserPromptSubmit", "prompt": REAL_PROMPT, "cwd": self.box.cwd},
            prompt_environ,
            self.box.home,
        )
        agent_code, agent_out, agent_err = run_main(
            claude_pretooluse_agent.main,
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Agent",
                "cwd": self.box.cwd,
                "tool_input": dict(AGENT_TOOL_INPUT),
            },
            self.box.environ({"CATSTACK_CAT_MODE_DEFAULT": "1", "CATSTACK_HOOK_MODE_CAT_MODE_DEFAULT": "warn"}),
            self.box.home,
        )

        self.assertEqual(0, prompt_code)
        self.assertEqual("", prompt_err)
        self.assertIn("cat-mode default is on", prompt_out)
        self.assertEqual(0, agent_code)
        self.assertEqual("", agent_err)
        self.assertIn("updatedInput", agent_out)

        metrics_dir = Path(prompt_environ["CATSTACK_HOOK_METRICS_DIR"])
        today = datetime.now(timezone.utc).date().isoformat()
        event_file = metrics_dir / f"events-{today}.jsonl"
        self.assertTrue(event_file.exists())
        rows = [json.loads(line) for line in event_file.read_text(encoding="utf-8").splitlines()]
        finding_rows = [row for row in rows if row["rule_id"]]
        self.assertEqual(2, len(finding_rows))
        self.assertEqual(
            ["cat-mode-default.agent-prompt", "cat-mode-default.prompt-context"],
            sorted(row["rule_id"] for row in finding_rows),
        )
        self.assertTrue(all(row["hook"] == "cat-mode-default" for row in finding_rows))
        self.assertTrue(all(row["mode"] == "warn" for row in finding_rows))
        self.assertTrue(all(row["mode_source"] == "override" for row in finding_rows))
        self.assertTrue(all(row["action"] == "warned" for row in finding_rows))


if __name__ == "__main__":
    unittest.main()
