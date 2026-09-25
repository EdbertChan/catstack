#!/usr/bin/env python3
"""SDK mode and event-row tests for explicit-failures."""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HOOK_DIR = Path(__file__).resolve().parents[1]
FIXTURES = HOOK_DIR / "tests" / "fixtures"
sys.path.insert(0, str(HOOK_DIR))

import claude_pretooluse  # noqa: E402
import detect  # noqa: E402

OVERRIDE_ENV = "CATSTACK_HOOK_MODE_EXPLICIT_FAILURES"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def write_payload(name: str, registry_path: Path) -> dict[str, object]:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "explicit-failures-sdk-mode",
        "registry_path": str(registry_path),
        "tool_name": "Write",
        "tool_input": {"file_path": f"/repo/{name}", "content": fixture(name)},
    }


@contextlib.contextmanager
def stdio(stdin_text: str):
    old_stdin, old_stdout, old_stderr = sys.stdin, sys.stdout, sys.stderr
    sys.stdin, sys.stdout, sys.stderr = io.StringIO(stdin_text), io.StringIO(), io.StringIO()
    try:
        yield
    finally:
        sys.stdin, sys.stdout, sys.stderr = old_stdin, old_stdout, old_stderr


def run_hook(payload: dict[str, object], env: dict[str, str]):
    with patch.dict(os.environ, env, clear=False), stdio(json.dumps(payload)):
        try:
            claude_pretooluse.main()
        except SystemExit as exc:
            return exc.code, sys.stderr.getvalue(), sys.stdout.getvalue()
        return 0, sys.stderr.getvalue(), sys.stdout.getvalue()


class ExplicitFailuresSdkModeTest(unittest.TestCase):
    def test_warn_override_changes_stop_response_to_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_path = self._registry(root, mode="stop")
            payload = write_payload("except_pass_fires.py", registry_path)

            stop_code, stop_err, stop_out = run_hook(
                payload,
                {"CATSTACK_HOOK_METRICS_DIR": str(root / "stop-metrics")},
            )
            warn_code, warn_err, warn_out = run_hook(
                payload,
                {
                    "CATSTACK_HOOK_METRICS_DIR": str(root / "warn-metrics"),
                    OVERRIDE_ENV: "warn",
                },
            )

        self.assertEqual(2, stop_code)
        self.assertIn("explicit-failures", stop_err)
        self.assertEqual("", stop_out)
        self.assertEqual(0, warn_code)
        self.assertEqual("", warn_err)
        body = json.loads(warn_out)
        output = body["hookSpecificOutput"]
        self.assertEqual("PreToolUse", output["hookEventName"])
        self.assertIn("explicit-failures", output["additionalContext"])

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_path = self._registry(root, mode="warn")
            metrics = root / "metrics"
            payload = write_payload("except_pass_fires.py", registry_path)

            findings = detect.detect(payload)
            code, err, out = run_hook(payload, {"CATSTACK_HOOK_METRICS_DIR": str(metrics)})
            rows = self._rows(metrics)

        self.assertEqual(0, code)
        self.assertEqual("", err)
        self.assertIn("explicit-failures", out)
        self.assertEqual(len(findings), len(rows))
        self.assertEqual(["explicit-failures.python-except"] * len(findings), [row["rule_id"] for row in rows])
        self.assertTrue(all(row["hook"] == "explicit-failures" for row in rows))
        self.assertTrue(all(row["action"] == "warned" for row in rows))

    def _registry(self, root: Path, mode: str) -> Path:
        path = root / "hooks.toml"
        path.write_text(
            "\n".join(
                [
                    "[thresholds]",
                    "min_closed_findings = 30",
                    "promote_max_ignore_rate = 0.02",
                    "demote_min_ignore_rate = 0.10",
                    "review_min_ignore_rate = 0.50",
                    "review_min_unchecked_rate = 0.05",
                    "followup_window_checks = 3",
                    "",
                    "[hooks.explicit-failures]",
                    f'mode = "{mode}"',
                    'why_mode = "habit"',
                    'summary = "Warns about code that hides errors."',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return path

    def _rows(self, metrics: Path) -> list[dict[str, object]]:
        files = list(metrics.glob("events-*.jsonl"))
        self.assertEqual(1, len(files))
        return [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]


if __name__ == "__main__":
    unittest.main()
