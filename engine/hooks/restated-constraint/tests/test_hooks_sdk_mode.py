from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HOOKS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOOKS_DIR))

import claude_prompt_submit  # noqa: E402


def transcript_with(user_texts: list[str]) -> str:
    tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    for i, text in enumerate(user_texts):
        tmp.write(
            json.dumps(
                {
                    "type": "user",
                    "timestamp": f"2000-01-01T00:{i:02d}:00Z",
                    "message": {"role": "user", "content": text},
                }
            )
            + "\n"
        )
    tmp.close()
    return tmp.name


def registry_with_mode(directory: str, mode: str) -> str:
    path = Path(directory) / "hooks.toml"
    path.write_text(
        f"""
[hooks.restated-constraint]
mode = "{mode}"
why_mode = "habit"
summary = "Notes that the user repeated an earlier rule."

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
    return str(path)


@contextlib.contextmanager
def stdio(stdin_text: str):
    old_stdin = sys.stdin
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdin = io.StringIO(stdin_text)
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    try:
        yield
    finally:
        sys.stdin = old_stdin
        sys.stdout = old_stdout
        sys.stderr = old_stderr


def invoke(payload: dict[str, object], env: dict[str, str]) -> tuple[int | None, str, str]:
    with mock.patch.dict(os.environ, env, clear=False), stdio(json.dumps(payload)):
        with unittest.TestCase().assertRaises(SystemExit) as caught:
            claude_prompt_submit.main()
        return caught.exception.code, sys.stdout.getvalue(), sys.stderr.getvalue()


def event_rows(directory: str) -> list[dict[str, object]]:
    files = list(Path(directory).glob("events-*.jsonl"))
    if not files:
        return []
    return [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]


class RestatedConstraintSdkModeTest(unittest.TestCase):
    def test_hook_mode_override_warn_changes_stop_response_to_warning(self) -> None:
        path = transcript_with([
            "make the holdings sheet stock agnostic, it should work for any ticker",
        ])
        try:
            with tempfile.TemporaryDirectory() as tmp:
                registry_path = registry_with_mode(tmp, "stop")
                payload = {
                    "hook_event_name": "Stop",
                    "prompt": "the parser must stay stock-agnostic. no ticker names in the code path.",
                    "transcript_path": path,
                    "registry_path": registry_path,
                    "session_id": "session-mode",
                }

                stop_code, stop_stdout, stop_stderr = invoke(
                    payload,
                    {"CATSTACK_HOOK_METRICS_DIR": str(Path(tmp) / "stop-metrics")},
                )
                warn_code, warn_stdout, warn_stderr = invoke(
                    payload,
                    {
                        "CATSTACK_HOOK_METRICS_DIR": str(Path(tmp) / "warn-metrics"),
                        "CATSTACK_HOOK_MODE_RESTATED_CONSTRAINT": "warn",
                    },
                )

            self.assertEqual(2, stop_code)
            self.assertEqual("", stop_stdout)
            self.assertIn("restated-constraint: this constraint was already named", stop_stderr)
            self.assertEqual(0, warn_code)
            self.assertEqual("", warn_stderr)
            body = json.loads(warn_stdout)
            self.assertIn(
                "restated-constraint: this constraint was already named",
                body["hookSpecificOutput"]["additionalContext"],
            )
        finally:
            os.unlink(path)

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        path = transcript_with([
            "make the holdings sheet stock agnostic, it should work for any ticker",
        ])
        try:
            with tempfile.TemporaryDirectory() as tmp:
                payload = {
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "the parser must stay stock-agnostic. no ticker names in the code path.",
                    "transcript_path": path,
                    "session_id": "session-events",
                }
                code, stdout, stderr = invoke(
                    payload,
                    {
                        "CATSTACK_HOOK_METRICS_DIR": tmp,
                        "CATSTACK_HOOK_MODE_RESTATED_CONSTRAINT": "warn",
                    },
                )
                rows = event_rows(tmp)

            self.assertEqual(0, code)
            self.assertEqual("", stderr)
            self.assertIn("stock agnostic", stdout)
            self.assertEqual(1, len(rows))
            self.assertEqual("restated-constraint", rows[0]["hook"])
            self.assertEqual("restated-constraint.shared-hyphenated-term", rows[0]["rule_id"])
            self.assertEqual("warn", rows[0]["mode"])
            self.assertEqual("override", rows[0]["mode_source"])
            self.assertEqual("warned", rows[0]["action"])
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
