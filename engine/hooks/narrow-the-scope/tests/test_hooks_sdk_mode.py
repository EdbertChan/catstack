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

import claude_posttooluse  # noqa: E402


def write_registry(path: Path, mode: str) -> None:
    path.write_text(
        f"""
[hooks.narrow-the-scope]
mode = "{mode}"
why_mode = "habit"
summary = "Warns about many edits with no check run."

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


def firing_payload(session_id: str, registry: Path | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "hook_event_name": "Stop",
        "session_id": session_id,
        "tool_name": "Edit",
        "tool_input": {"file_path": "/x/a.py"},
    }
    if registry is not None:
        payload["registry_path"] = str(registry)
    return payload


def run_claude(payload: dict[str, object]) -> tuple[int, str, str]:
    stdout = StringIO()
    stderr = StringIO()
    with patch.object(sys, "stdin", StringIO(json.dumps(payload))):
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                claude_posttooluse.main()
            except SystemExit as exc:
                return int(exc.code or 0), stdout.getvalue(), stderr.getvalue()
    return 0, stdout.getvalue(), stderr.getvalue()


def run_until_firing(session_id: str, registry: Path | None = None) -> tuple[int, str, str]:
    result = (0, "", "")
    for _ in range(3):
        result = run_claude(firing_payload(session_id, registry))
    return result


def event_rows(directory: Path) -> list[dict[str, object]]:
    today = datetime.now(timezone.utc).date().isoformat()
    path = directory / f"events-{today}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class NarrowTheScopeSdkModeTest(unittest.TestCase):
    def test_warn_override_changes_stop_registry_response_to_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = root / "hooks.toml"
            write_registry(registry, "stop")
            with patch.dict(
                os.environ,
                {
                    "CATSTACK_NARROW_THE_SCOPE_STATE_DIR": str(root / "state-stop"),
                    "CATSTACK_HOOK_METRICS_DIR": str(root / "metrics-stop"),
                },
                clear=False,
            ):
                stop_code, stop_out, stop_err = run_until_firing("narrow-stop", registry)
            with patch.dict(
                os.environ,
                {
                    "CATSTACK_NARROW_THE_SCOPE_STATE_DIR": str(root / "state-warn"),
                    "CATSTACK_HOOK_METRICS_DIR": str(root / "metrics-warn"),
                    "CATSTACK_HOOK_MODE_NARROW_THE_SCOPE": "warn",
                },
                clear=False,
            ):
                warn_code, warn_out, warn_err = run_until_firing("narrow-warn", registry)

        self.assertEqual(2, stop_code)
        self.assertEqual("", stop_out)
        self.assertIn("narrow-the-scope: 3 edits to /x/a.py", stop_err)
        self.assertEqual(0, warn_code)
        self.assertEqual("", warn_err)
        warning = json.loads(warn_out)
        self.assertIn(
            "narrow-the-scope: 3 edits to /x/a.py",
            warning["hookSpecificOutput"]["additionalContext"],
        )

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            metrics = root / "metrics"
            with patch.dict(
                os.environ,
                {
                    "CATSTACK_NARROW_THE_SCOPE_STATE_DIR": str(root / "state"),
                    "CATSTACK_HOOK_METRICS_DIR": str(metrics),
                    "CATSTACK_HOOK_MODE_NARROW_THE_SCOPE": "warn",
                },
                clear=False,
            ):
                code, out, err = run_until_firing("narrow-events")
                rows = event_rows(metrics)

        finding_rows = [row for row in rows if row["rule_id"]]
        self.assertEqual(0, code)
        self.assertEqual("", err)
        self.assertIn("narrow-the-scope", out)
        self.assertEqual(1, len(finding_rows))
        self.assertEqual("narrow-the-scope.edit-streak", finding_rows[0]["rule_id"])
        self.assertEqual("narrow-the-scope", finding_rows[0]["hook"])
        self.assertEqual("warn", finding_rows[0]["mode"])
        self.assertEqual("override", finding_rows[0]["mode_source"])
        self.assertEqual("warned", finding_rows[0]["action"])


if __name__ == "__main__":
    unittest.main()
