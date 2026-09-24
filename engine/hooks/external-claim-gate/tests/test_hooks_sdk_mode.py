from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HOOK_DIR = Path(__file__).resolve().parents[1]
HOOK = HOOK_DIR / "claude_pretooluse.py"
sys.path.insert(0, str(HOOK_DIR.parent / "_sdk"))
sys.path.insert(0, str(HOOK_DIR))

CAUSE = "The worker crashes because the cache is never invalidated."
RESOLUTION = "Verified, the upload succeeds after the retry change."


def bash_payload(command: str, cwd: str, session_id: str = "external-claim-gate-test") -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": session_id,
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": cwd,
    }


def run_hook(payload: dict, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    hook_env = os.environ.copy()
    hook_env.update(env)
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        env=hook_env,
    )


def event_rows(metrics_dir: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted(metrics_dir.glob("events-*.jsonl")):
        rows.extend(json.loads(line) for line in path.read_text().splitlines() if line.strip())
    return rows


class TestSdkModeAndEvents(unittest.TestCase):
    def test_mode_override_warn_changes_stop_to_warning(self) -> None:
        """The override downgrades the registry stop to a warning.

        This command exits 2 under the registry mode, so exit 0 plus a
        warning is the override taking effect. The hook does not ask the
        runtime for warn_stderr, so the warning rides on stdout."""
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as metrics:
            result = run_hook(
                bash_payload(f"gh issue create --title Crash --body '{CAUSE}'", d),
                {
                    "CATSTACK_HOOK_MODE_EXTERNAL_CLAIM_GATE": "warn",
                    "CATSTACK_HOOK_METRICS_DIR": metrics,
                },
            )
            rows = event_rows(Path(metrics))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertNotIn("permissionDecision", output)
        self.assertIn("external-claim-gate", output["additionalContext"])
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]["mode"], "warn")
        self.assertEqual(rows[0]["mode_source"], "override")
        self.assertEqual(rows[0]["action"], "warned")

    def test_writes_one_event_row_per_finding_with_rule_id(self) -> None:
        command = (
            f"gh issue comment 1 --body '{CAUSE}'; "
            f"gh issue comment 2 --body '{RESOLUTION}'"
        )
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as metrics:
            result = run_hook(
                bash_payload(command, d, session_id="external-claim-gate-events"),
                {"CATSTACK_HOOK_METRICS_DIR": metrics},
            )
            rows = event_rows(Path(metrics))

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(len(rows), 2, rows)
        self.assertEqual({row["hook"] for row in rows}, {"external-claim-gate"})
        self.assertEqual(
            {row["rule_id"] for row in rows},
            {"external-claim-gate.unverified-claim"},
        )


class TestDetectorFailureIsNeverSilent(unittest.TestCase):
    """A detector crash is a third outcome, not a clean pass.

    detect() catches every exception out of evaluate(). Both arms of that
    handler have to say something: the arm that sees a gh write reports an
    unchecked finding, and the arm that does not has to name the failure on
    stderr rather than allow the command without a word."""

    def detect_with_broken_evaluate(self, command: str) -> tuple[list, str]:
        import detect as gate  # noqa: PLC0415

        event = {
            "hook_event_name": "PreToolUse",
            "session_id": "detector-failure",
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "cwd": os.getcwd(),
        }
        captured = io.StringIO()
        with mock.patch.object(gate, "evaluate", side_effect=RuntimeError("boom")):
            with contextlib.redirect_stderr(captured):
                findings = gate.detect(event)
        return findings, captured.getvalue()

    def test_failure_naming_a_gh_write_reports_unchecked(self) -> None:
        findings, stderr = self.detect_with_broken_evaluate(
            f"gh issue create --title Crash --body '{CAUSE}'"
        )

        self.assertEqual(len(findings), 1, findings)
        self.assertIn("the detector failed", findings[0].message)
        self.assertEqual(stderr, "")

    def test_failure_naming_no_gh_write_says_so_on_stderr(self) -> None:
        findings, stderr = self.detect_with_broken_evaluate("echo hello")

        self.assertEqual(findings, [])
        self.assertIn("external-claim-gate", stderr)
        self.assertIn("the detector failed", stderr)
        self.assertIn("RuntimeError", stderr)


if __name__ == "__main__":
    unittest.main()
