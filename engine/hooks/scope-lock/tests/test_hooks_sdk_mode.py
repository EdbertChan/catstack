from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

HOOK_DIR = Path(__file__).resolve().parents[1]
PROMPT_ENTRYPOINT = HOOK_DIR / "claude_prompt_scope.py"
PRETOOL_ENTRYPOINT = HOOK_DIR / "claude_pretool_scope.py"
CORRECTION = "wtf are you doing? Just fix it locally."


def write_registry(directory: Path, mode: str) -> Path:
    path = directory / "hooks.toml"
    path.write_text(
        textwrap.dedent(
            f"""
            [hooks.scope-lock]
            mode = "{mode}"
            why_mode = "attention"
            summary = "Test registry entry."

            [hooks.scope-lock.rule_modes]
            "scope-lock.prompt-instruction" = "warn"
            "scope-lock.reflection-acknowledged" = "warn"

            [thresholds]
            min_closed_findings = 30
            promote_max_ignore_rate = 0.02
            demote_min_ignore_rate = 0.10
            review_min_ignore_rate = 0.50
            review_min_unchecked_rate = 0.05
            followup_window_checks = 3
            """
        ).lstrip(),
        encoding="utf-8",
    )
    return path


def run_entrypoint(entrypoint: Path, payload: dict[str, object], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    hook_env = os.environ.copy()
    hook_env.update(env)
    return subprocess.run(
        [sys.executable, str(entrypoint)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        env=hook_env,
    )


def write_transcript(path: Path, prompt: str) -> None:
    path.write_text(
        "\n".join(
            json.dumps(row)
            for row in (
                {
                    "type": "user",
                    "message": {"role": "user", "content": "Please complete the requested work."},
                },
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "tool_use", "name": "Write", "input": {}}],
                    },
                },
                {"type": "user", "message": {"role": "user", "content": prompt}},
            )
        )
        + "\n",
        encoding="utf-8",
    )


def arm_scope_lock(root: Path, registry: Path, env: dict[str, str], session_id: str) -> Path:
    transcript = root / f"{session_id}.jsonl"
    write_transcript(transcript, CORRECTION)
    payload = {
        "session_id": session_id,
        "transcript_path": str(transcript),
        "prompt": CORRECTION,
        "registry_path": str(registry),
    }
    result = run_entrypoint(PROMPT_ENTRYPOINT, payload, env)
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return transcript


def pretool_payload(transcript: Path, registry: Path, session_id: str) -> dict[str, object]:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": session_id,
        "transcript_path": str(transcript),
        "tool_name": "Write",
        "registry_path": str(registry),
    }


def event_rows(metrics_dir: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted(metrics_dir.glob("events-*.jsonl")):
        rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return rows


class TestSdkModeAndEvents(unittest.TestCase):
    def test_mode_override_warn_changes_stop_to_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = write_registry(root, "stop")
            metrics = root / "metrics"
            env = {
                "CATSTACK_REFLECT_ENFORCEMENT": "1",
                "CATSTACK_HOOK_METRICS_DIR": str(metrics),
                "CATSTACK_HOOK_MODE_SCOPE_LOCK": "warn",
                "SCOPE_LOCK_STATE_DIR": str(root / "state"),
            }
            transcript = arm_scope_lock(root, registry, env, "scope-lock-mode")
            result = run_entrypoint(
                PRETOOL_ENTRYPOINT,
                pretool_payload(transcript, registry, "scope-lock-mode"),
                env,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)
        body = json.loads(result.stdout)
        self.assertIn("SCOPE CONTRACT:", body["hookSpecificOutput"]["additionalContext"])

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = write_registry(root, "stop")
            metrics = root / "metrics"
            env = {
                "CATSTACK_REFLECT_ENFORCEMENT": "1",
                "CATSTACK_HOOK_METRICS_DIR": str(metrics),
                "CATSTACK_HOOK_MODE_SCOPE_LOCK": "",
                "SCOPE_LOCK_STATE_DIR": str(root / "state"),
            }
            transcript = arm_scope_lock(root, registry, env, "scope-lock-events")
            for path in metrics.glob("events-*.jsonl"):
                path.unlink()
            result = run_entrypoint(
                PRETOOL_ENTRYPOINT,
                pretool_payload(transcript, registry, "scope-lock-events"),
                env,
            )
            rows = event_rows(metrics)

        self.assertEqual(2, result.returncode, result.stderr)
        finding_rows = [row for row in rows if row["rule_id"]]
        self.assertEqual(1, len(finding_rows), rows)
        self.assertEqual("scope-lock", finding_rows[0]["hook"])
        self.assertEqual("scope-lock.contract-required", finding_rows[0]["rule_id"])
        self.assertEqual("stopped", finding_rows[0]["action"])


if __name__ == "__main__":
    unittest.main()
