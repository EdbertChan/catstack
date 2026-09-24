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
CLAUDE_PRETOOL = HOOK_DIR / "claude_pretooluse_log.py"
CODEX_PROMPT = HOOK_DIR / "codex_prompt_submit.py"


def write_registry(directory: Path) -> Path:
    path = directory / "hooks.toml"
    path.write_text(
        textwrap.dedent(
            """
            [hooks.skill-usage-log]
            mode = "off"
            why_mode = "habit"
            summary = "Test registry entry."

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


def run_entrypoint(
    entrypoint: Path,
    payload: dict[str, object],
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
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


def event_rows(metrics_dir: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted(metrics_dir.glob("events-*.jsonl")):
        rows.extend(
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    return rows


class TestSdkModeAndEvents(unittest.TestCase):
    def test_mode_override_warn_changes_off_to_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = write_registry(root)
            metrics = root / "metrics"
            result = run_entrypoint(
                CLAUDE_PRETOOL,
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "skill-mode",
                    "tool_name": "Skill",
                    "tool_input": {"skill": "diu"},
                    "registry_path": str(registry),
                },
                {
                    "CATSTACK_HOOK_METRICS_DIR": str(metrics),
                    "CATSTACK_HOOK_MODE_SKILL_USAGE_LOG": "warn",
                },
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)
        body = json.loads(result.stdout)
        self.assertIn("Skill used: diu", body["hookSpecificOutput"]["additionalContext"])

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = write_registry(root)
            metrics = root / "metrics"
            skill_dir = root / ".codex" / "skills" / "reflect"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("# reflect\n", encoding="utf-8")
            result = run_entrypoint(
                CODEX_PROMPT,
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "skill-events",
                    "prompt": "/reflect and $reflect",
                    "registry_path": str(registry),
                },
                {
                    "HOME": str(root),
                    "CATSTACK_HOOK_METRICS_DIR": str(metrics),
                    "CATSTACK_HOOK_MODE_SKILL_USAGE_LOG": "",
                },
            )
            rows = event_rows(metrics)

        self.assertEqual((0, "", ""), (result.returncode, result.stdout, result.stderr))
        finding_rows = [row for row in rows if row.get("rule_id")]
        self.assertEqual(2, len(finding_rows), rows)
        self.assertEqual(
            {"skill-usage-log.slash", "skill-usage-log.mention"},
            {row["rule_id"] for row in finding_rows},
        )
        self.assertEqual({"skill-usage-log"}, {row["hook"] for row in finding_rows})
        self.assertEqual({"off"}, {row["mode"] for row in finding_rows})
        self.assertEqual({"silent"}, {row["action"] for row in finding_rows})


if __name__ == "__main__":
    unittest.main()
