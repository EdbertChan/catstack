from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

HOOK_DIR = Path(__file__).resolve().parents[1]
CODEX_ENTRYPOINT = HOOK_DIR / "codex_prompt_submit.py"
PROCEDURE = "# Repair widget\n\n## Steps\n\n1. Observe the widget.\n2. Repair the widget.\n"


class PlaybookRouterSdkModeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.repo = self.root / "repo"
        self.metrics = self.root / "metrics"
        self.home.mkdir()
        (self.repo / ".git").mkdir(parents=True)
        self._write(self.repo / "playbooks/repair-widget.md", PROCEDURE)

    def test_mode_override_warn_changes_registry_stop_to_warning(self) -> None:
        registry_path = self._registry("stop")
        payload = self._payload(registry_path)

        stopped = self._run(payload, metrics_dir=self.root / "stopped-metrics")
        warned = self._run(
            payload,
            metrics_dir=self.root / "warned-metrics",
            env={"CATSTACK_HOOK_MODE_PLAYBOOK_ROUTER": "warn"},
        )

        self.assertEqual(0, stopped.returncode, stopped.stderr)
        stopped_body = json.loads(stopped.stdout)
        self.assertEqual("block", stopped_body["decision"])
        self.assertIn("Repair the widget.", stopped_body["reason"])

        self.assertEqual(0, warned.returncode, warned.stderr)
        warned_body = json.loads(warned.stdout)
        self.assertNotIn("decision", warned_body)
        self.assertIn("Repair the widget.", warned_body["hookSpecificOutput"]["additionalContext"])

    def test_each_finding_writes_one_event_row_with_rule_id(self) -> None:
        result = self._run(self._payload())

        self.assertEqual(0, result.returncode, result.stderr)
        rows = self._rows(self.metrics)
        self.assertEqual(1, len(rows))
        self.assertEqual("playbook-router", rows[0]["hook"])
        self.assertEqual("playbook-router.named-playbook", rows[0]["rule_id"])
        self.assertEqual("warn", rows[0]["mode"])
        self.assertEqual("registry", rows[0]["mode_source"])
        self.assertEqual("warned", rows[0]["action"])

    def _payload(self, registry_path: str | None = None) -> dict[str, object]:
        payload: dict[str, object] = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "playbook-router-sdk-mode",
            "cwd": str(self.repo),
            "prompt": "repair widget",
        }
        if registry_path is not None:
            payload["registry_path"] = registry_path
        return payload

    def _run(
        self,
        payload: dict[str, object],
        metrics_dir: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        merged_env = os.environ.copy()
        merged_env.update({
            "HOME": str(self.home),
            "CATSTACK_HOOK_METRICS_DIR": str(metrics_dir or self.metrics),
        })
        merged_env.update(env or {})
        return subprocess.run(
            [sys.executable, str(CODEX_ENTRYPOINT)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            cwd=self.repo,
            env=merged_env,
            timeout=10,
        )

    def _registry(self, mode: str) -> str:
        path = self.root / f"hooks-{mode}.toml"
        path.write_text(
            textwrap.dedent(
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
                """
            ).lstrip(),
            encoding="utf-8",
        )
        return str(path)

    def _rows(self, directory: Path) -> list[dict[str, object]]:
        files = list(directory.glob("events-*.jsonl"))
        self.assertEqual(1, len(files))
        return [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]

    def _write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
