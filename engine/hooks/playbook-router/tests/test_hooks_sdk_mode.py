from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HOOK_DIR = Path(__file__).resolve().parents[1]
CODEX_ENTRYPOINT = HOOK_DIR / "codex_prompt_submit.py"
PROCEDURE = "# Repair widget\n\n## Steps\n\n1. Observe the widget.\n2. Repair the widget.\n"
RULE_ID = "playbook-router.named-playbook"
OVERRIDE_ENV = "CATSTACK_HOOK_MODE_PLAYBOOK_ROUTER"


def write_registry(path: Path, mode: str) -> None:
    path.write_text(
        f"""
[hooks.playbook-router]
mode = "{mode}"
why_mode = "habit"
summary = "Adds the steps of a named playbook."

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


class PlaybookRouterSdkModeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.repo = self.root / "repo"
        self.metrics = self.root / "metrics"
        self.registry = self.root / "hooks.toml"
        self.home.mkdir()
        (self.repo / ".git").mkdir(parents=True)
        self.write(self.repo / "playbooks/repair-widget.md", PROCEDURE)

    def write(self, path: Path, content: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def payload(self, session_id: str) -> dict[str, object]:
        return {
            "hook_event_name": "UserPromptSubmit",
            "session_id": session_id,
            "prompt": "repair widget",
            "cwd": str(self.repo),
            "registry_path": str(self.registry),
        }

    def run_codex(self, payload: dict[str, object], env: dict[str, str] | None = None):
        merged_env = os.environ.copy()
        merged_env.update({
            "HOME": str(self.home),
            "CATSTACK_HOOK_METRICS_DIR": str(self.metrics),
        })
        if env:
            merged_env.update(env)
        return subprocess.run(
            [sys.executable, str(CODEX_ENTRYPOINT)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=merged_env,
            cwd=self.repo,
            timeout=10,
        )

    def event_rows(self) -> list[dict[str, object]]:
        return [
            json.loads(line)
            for path in self.metrics.glob("events-*.jsonl")
            for line in path.read_text(encoding="utf-8").splitlines()
        ]

    def test_warn_override_changes_stop_registry_response_to_warning(self) -> None:
        write_registry(self.registry, "stop")
        stopped = self.run_codex(self.payload("playbook-router-stop"))
        warned = self.run_codex(
            self.payload("playbook-router-warn"),
            {OVERRIDE_ENV: "warn"},
        )

        self.assertEqual(0, stopped.returncode, stopped.stderr)
        self.assertEqual("", stopped.stderr)
        stop_body = json.loads(stopped.stdout)
        self.assertEqual("block", stop_body["decision"])
        self.assertIn("Repair the widget.", stop_body["reason"])

        self.assertEqual(0, warned.returncode, warned.stderr)
        self.assertEqual("", warned.stderr)
        warn_body = json.loads(warned.stdout)
        self.assertNotIn("decision", warn_body)
        self.assertIn("Repair the widget.", warn_body["hookSpecificOutput"]["additionalContext"])

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        write_registry(self.registry, "warn")
        result = self.run_codex(self.payload("playbook-router-events"))
        rows = self.event_rows()

        finding_rows = [row for row in rows if row["rule_id"] == RULE_ID]
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)
        self.assertIn("Repair the widget.", result.stdout)
        self.assertEqual(1, len(finding_rows), rows)
        self.assertEqual("playbook-router", finding_rows[0]["hook"])
        self.assertEqual("warn", finding_rows[0]["mode"])
        self.assertEqual("registry", finding_rows[0]["mode_source"])
        self.assertEqual("warned", finding_rows[0]["action"])


if __name__ == "__main__":
    unittest.main()
