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
from unittest.mock import patch

HOOK_DIR = Path(__file__).resolve().parents[1]
HOOK = HOOK_DIR / "claude_pretooluse.py"

sys.path.insert(0, str(HOOK_DIR))

import detect as gate  # noqa: E402

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
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as metrics:
            result = run_hook(
                bash_payload(f"gh issue create --title Crash --body '{CAUSE}'", d),
                {
                    "CATSTACK_HOOK_MODE_EXTERNAL_CLAIM_GATE": "warn",
                    "CATSTACK_HOOK_METRICS_DIR": metrics,
                },
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual("", result.stderr)
        rendered = json.loads(result.stdout)
        additional_context = rendered["hookSpecificOutput"]["additionalContext"]
        self.assertIn("external-claim-gate", additional_context)
        self.assertIn(CAUSE, additional_context)

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


class TestDetectorCrashIsReported(unittest.TestCase):
    """A crash inside evaluate() has to name itself on stderr before detect()
    turns it into an unchecked finding.

    The pre-SDK entrypoint printed `catstack-hook-error external-claim-gate:`
    on this path. Moving the handler into detect() dropped that line, which
    left the only record of a detector bug in a finding whose text callers
    read as a gh-write problem rather than a hook problem."""

    def _detect(self, command: str) -> tuple[list[object], str]:
        event = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": os.getcwd()}
        stderr = io.StringIO()
        with patch.object(gate, "evaluate", side_effect=RuntimeError("boom")):
            with contextlib.redirect_stderr(stderr):
                findings = gate.detect(event)
        return findings, stderr.getvalue()

    def test_crash_on_a_gh_write_is_logged_and_blocks(self) -> None:
        findings, stderr = self._detect("gh issue create --title Crash --body hi")

        self.assertIn("catstack-hook-error external-claim-gate: RuntimeError: boom", stderr)
        self.assertEqual([f.rule_id for f in findings], ["external-claim-gate.unchecked-body"])

    def test_crash_without_a_gh_write_is_logged_and_allows(self) -> None:
        findings, stderr = self._detect("ls -la")

        self.assertIn("catstack-hook-error external-claim-gate: RuntimeError: boom", stderr)
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
