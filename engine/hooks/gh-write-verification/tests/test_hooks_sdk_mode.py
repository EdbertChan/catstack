from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from test_hooks import STOP_CHECK, bash_payload, run_entrypoint, transcript

HOOK_NAME = "gh-write-verification"
MODE_ENV = "CATSTACK_HOOK_MODE_GH_WRITE_VERIFICATION"


class SdkModeTest(unittest.TestCase):
    def test_warn_override_changes_stop_response_to_warning(self) -> None:
        path = transcript(["gh pr merge 291 --squash --admin"])
        try:
            with tempfile.TemporaryDirectory() as metrics_dir:
                result = run_entrypoint(
                    STOP_CHECK,
                    {"transcript_path": path, "session_id": "session-warn-override"},
                    {MODE_ENV: "warn", "CATSTACK_HOOK_METRICS_DIR": metrics_dir},
                )
        finally:
            os.unlink(path)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)
        body = json.loads(result.stdout)
        output = body["hookSpecificOutput"]
        self.assertEqual("Stop", output["hookEventName"])
        self.assertIn("verify_pr_landed_on_trunk.sh", output["additionalContext"])

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        payload = bash_payload("gh pr edit 291 --base main >/dev/null 2>&1")
        payload["session_id"] = "session-event-rows"

        with tempfile.TemporaryDirectory() as metrics_dir:
            result = run_entrypoint(
                os.path.join(os.path.dirname(STOP_CHECK), "claude_pretooluse.py"),
                payload,
                {MODE_ENV: "stop", "CATSTACK_HOOK_METRICS_DIR": metrics_dir},
            )
            rows = self._event_rows(metrics_dir)

        self.assertEqual(2, result.returncode, result.stderr)
        self.assertEqual(
            [
                "gh-write-verification.broken-pr-edit",
                "gh-write-verification.silenced-mutation",
            ],
            [row["rule_id"] for row in rows],
        )
        self.assertTrue(all(row["hook"] == HOOK_NAME for row in rows))

    def _event_rows(self, metrics_dir: str) -> list[dict[str, object]]:
        files = list(Path(metrics_dir).glob("events-*.jsonl"))
        self.assertEqual(1, len(files))
        return [
            json.loads(line)
            for line in files[0].read_text(encoding="utf-8").splitlines()
        ]


if __name__ == "__main__":
    unittest.main()
