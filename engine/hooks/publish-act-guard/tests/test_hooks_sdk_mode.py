import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


HOOK_DIR = Path(__file__).resolve().parents[1]
SCRIPT = HOOK_DIR / "claude_pretooluse.py"
RULE_ID = "publish-act-guard.helper-publish"


def payload(command="git push -u origin HEAD", *, session_id="session-1"):
    return {
        "hook_event_name": "PreToolUse",
        "session_id": session_id,
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "subagent_id": "a4b7b959ce73515c9",
    }


class HooksSdkMode(unittest.TestCase):
    def run_hook(self, event, *, mode=None):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        tmpdir = root / "tmp"
        metrics = root / "metrics"
        tmpdir.mkdir()
        metrics.mkdir()
        (tmpdir / "publish-act-guard-liveness.json").write_text(
            json.dumps({"state": "live", "at": time.time()}),
            encoding="utf-8",
        )
        (tmpdir / "publish-act-guard-publishers.json").write_text(
            json.dumps({event.get("session_id"): {"other-agent": time.time()}}),
            encoding="utf-8",
        )
        env = os.environ.copy()
        env["TMPDIR"] = str(tmpdir)
        env["CATSTACK_HOOK_METRICS_DIR"] = str(metrics)
        if mode is None:
            env.pop("CATSTACK_HOOK_MODE_PUBLISH_ACT_GUARD", None)
        else:
            env["CATSTACK_HOOK_MODE_PUBLISH_ACT_GUARD"] = mode
        completed = subprocess.run(
            [sys.executable, str(SCRIPT)],
            input=json.dumps(event),
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        rows = []
        for path in metrics.glob("events-*.jsonl"):
            rows.extend(
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
        return completed, rows

    def test_warn_override_changes_stop_response_to_warning(self):
        stopped, _rows = self.run_hook(payload(session_id="stop-session"))
        self.assertEqual(stopped.returncode, 2)
        self.assertIn("publish-act-guard", stopped.stderr)

        warned, _rows = self.run_hook(payload(session_id="warn-session"), mode="warn")
        self.assertEqual(warned.returncode, 0)
        self.assertIn("additionalContext", warned.stdout)
        self.assertIn("publish-act-guard", warned.stdout)
        self.assertEqual(warned.stderr, "")

    def test_writes_one_event_row_per_finding_with_rule_id(self):
        completed, rows = self.run_hook(payload(session_id="events-session"))
        self.assertEqual(completed.returncode, 2)
        finding_rows = [
            row
            for row in rows
            if row.get("hook") == "publish-act-guard" and row.get("action") == "stopped"
        ]
        self.assertEqual(len(finding_rows), 1)
        self.assertEqual(finding_rows[0]["rule_id"], RULE_ID)


if __name__ == "__main__":
    unittest.main()
