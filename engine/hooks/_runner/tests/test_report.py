from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

RUNNER_DIR = Path(__file__).resolve().parents[1]
REPORT = RUNNER_DIR / "report.py"


class ReportCli(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.metrics = Path(self.tmp.name) / "metrics"
        self.metrics.mkdir(parents=True)
        self.log = self.metrics / "runs.jsonl"

    def env(self) -> dict[str, str]:
        return {**os.environ, "HOME": str(self.home), "CATSTACK_HOOK_METRICS_DIR": str(self.metrics)}

    def run_report(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(REPORT), *args],
            capture_output=True,
            text=True,
            env=self.env(),
            timeout=10,
        )

    def write_json(self, path: Path, data: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")

    def row(self, harness: str, hook: str, script: str, outcome: str, **extra: object) -> dict[str, object]:
        data: dict[str, object] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "harness": harness,
            "hook": hook,
            "script": script,
            "event": "UserPromptSubmit",
            "session_id": "s1",
            "outcome": outcome,
            "exit_code": 0,
            "duration_ms": 10,
            "stdout_bytes": 0,
            "stderr_tail": "",
        }
        data.update(extra)
        return data

    def seed_configs(self) -> None:
        self.write_json(
            self.home / ".claude" / "settings.json",
            {
                "hooks": {
                    "UserPromptSubmit": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python3 $HOME/.claude/hooks/_runner/run.py --timeout 9 hook-a/a.py",
                                }
                            ]
                        }
                    ]
                }
            },
        )
        self.write_json(
            self.home / ".cursor" / "hooks.json",
            {
                "hooks": {
                    "beforeSubmitPrompt": [
                        {
                            "command": "python3 $HOME/.cursor/hooks/_runner/run.py --timeout 9 hook-b/b.py",
                        }
                    ]
                }
            },
        )
        self.write_json(
            self.home / ".codex" / "hooks.json",
            {
                "hooks": {
                    "UserPromptSubmit": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python3 $HOME/.codex/hooks/_runner/run.py --timeout 9 hook-c/c.py",
                                }
                            ]
                        }
                    ]
                }
            },
        )

    def write_rows(self, rows: list[dict[str, object]], malformed: bool = False) -> None:
        with self.log.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
            if malformed:
                handle.write("{bad\n")

    def event_row(
        self,
        hook: str,
        rule_id: str,
        action: str,
        *,
        outcome: str | None = None,
        mode: str = "warn",
        duration_ms: int = 10,
        finding_id: str = "finding",
    ) -> dict[str, object]:
        data: dict[str, object] = {
            "schema": "catstack.hook.finding.v1",
            "ts": datetime.now(timezone.utc).isoformat(),
            "machine": "fixture",
            "harness": "codex",
            "session_id": "s-events",
            "hook": hook,
            "rule_id": rule_id,
            "subject_hash": "subject",
            "mode": mode,
            "mode_source": "registry",
            "action": action,
            "finding_id": finding_id,
            "duration_ms": duration_ms,
        }
        if outcome is not None:
            data["outcome"] = outcome
        return data

    def closed_events(
        self,
        hook: str,
        rule_id: str,
        *,
        mode: str,
        action: str,
        outcomes: list[str],
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for index, outcome in enumerate(outcomes):
            finding_id = f"{hook}-{rule_id}-{index}"
            rows.append(
                self.event_row(
                    hook,
                    rule_id,
                    action,
                    mode=mode,
                    duration_ms=index + 1,
                    finding_id=finding_id,
                )
            )
            rows.append(
                self.event_row(
                    hook,
                    rule_id,
                    "followup",
                    outcome=outcome,
                    mode=mode,
                    duration_ms=0,
                    finding_id=finding_id,
                )
            )
        return rows

    def write_events(self, rows: list[dict[str, object]], malformed: bool = False) -> Path:
        path = self.metrics / f"events-{datetime.now(timezone.utc).date().isoformat()}.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
            if malformed:
                handle.write("{bad\n")
        return path

    def stage(self, action: str, reason: str, job: str, hours_ago: float = 3, hook: str = "wrong-check-reflect") -> dict[str, object]:
        ts = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        return {"schema": "catstack.hook_event.v1", "ts": ts.isoformat(), "harness": "claude", "hook": hook,
                "rule_id": "", "mode_source": "stage", "action": action, "reason": reason, "finding_id": job}

    def delivered(self, verdict: str, job: str, hook: str = "wrong-check-reflect") -> dict[str, object]:
        return {"schema": "catstack.hook_event.v1", "ts": datetime.now(timezone.utc).isoformat(), "harness": "judge",
                "hook": hook, "rule_id": hook, "mode_source": "judge", "action": verdict, "finding_id": job}

    def test_judge_report_counts_every_stage_and_each_leak(self) -> None:
        self.write_events(
            [
                self.stage("judge_skipped", "already_prompted", "s1"),
                self.stage("judge_skipped", "already_prompted", "s2"),
                self.stage("judge_skipped", "gate_off", "s3"),
                self.stage("judge_queued", "transcript", "delivered-hit"),
                self.stage("judge_finished", "hit", "delivered-hit"),
                self.delivered("hit", "delivered-hit"),
                self.stage("judge_queued", "transcript", "lost-hit"),
                self.stage("judge_finished", "hit", "lost-hit"),
                self.stage("judge_queued", "no_transcript", "no-path"),
                self.stage("judge_finished", "clean", "no-path"),
                self.stage("judge_queued", "transcript", "hung"),
                self.stage("judge_queued", "transcript", "fresh", hours_ago=0.1),
            ]
        )
        result = self.run_report("--judge", "--json", "--since", "1d")
        self.assertEqual(result.returncode, 0, result.stderr)
        [row] = json.loads(result.stdout)["hooks"]
        self.assertEqual(row["skipped"], {"already_prompted": 2, "gate_off": 1})
        self.assertEqual(row["queued"], 5)
        self.assertEqual(row["finished"], {"hit": 2, "clean": 1, "unchecked": 0})
        self.assertEqual(row["delivered"], {"hit": 1, "clean": 0, "unchecked": 0})
        self.assertEqual(
            {key: row[key] for key in ("no_transcript", "stuck", "undelivered", "undelivered_hits")},
            {"no_transcript": 1, "stuck": 1, "undelivered": 2, "undelivered_hits": 1},
        )

    def test_judge_check_fails_on_a_leak_and_passes_when_every_verdict_is_delivered(self) -> None:
        self.write_events([self.stage("judge_queued", "transcript", "j"), self.stage("judge_finished", "hit", "j")])
        leaked = self.run_report("--judge", "--check", "--since", "1d")
        self.assertEqual(leaked.returncode, 1, leaked.stdout + leaked.stderr)
        self.assertIn("LEAK: 1 judge job(s)", leaked.stdout)
        self.write_events(
            [self.stage("judge_queued", "transcript", "j"), self.stage("judge_finished", "hit", "j"), self.delivered("hit", "j")]
        )
        clean = self.run_report("--judge", "--check", "--since", "1d")
        self.assertEqual(clean.returncode, 0, clean.stdout + clean.stderr)
        self.assertNotIn("LEAK", clean.stdout)

    def test_judge_rows_stay_out_of_the_rule_table(self) -> None:
        self.seed_configs()
        self.write_events([self.stage("judge_skipped", "gate_off", "s1")])
        result = self.run_report("--since", "1d")
        self.assertNotIn("judge_skipped", result.stdout)
        self.assertNotIn("wrong-check-reflect", result.stdout)

    def test_codex_notify_scripts_count_as_registered_hooks(self) -> None:
        runner = str(self.home / ".codex" / "hooks" / "_runner" / "run.py")
        direct = str(self.home / ".codex" / "hooks" / "auto-pr" / "codex_notify.py")
        config = self.home / ".codex" / "config.toml"
        config.parent.mkdir(parents=True, exist_ok=True)
        argv = ["python3", runner, "--notify", "--timeout", "59.5", "llm-judge/codex_notify.py", "python3", direct]
        config.write_text("notify = " + json.dumps(argv) + "\n", encoding="utf-8")
        self.write_rows([self.row("codex", "llm-judge", "codex_notify.py", "silent", event="agent-turn-complete")])
        result = self.run_report("--runs", "--since", "24h")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("codex llm-judge/codex_notify.py 1 0 1", result.stdout)
        self.assertIn("codex auto-pr/codex_notify.py no record", result.stdout)

    def test_skills_report_counts_uses_per_harness_and_lists_unused_installed_skills(self) -> None:
        for root, name in ((".claude/skills", "diu"), (".claude/skills", "idle"), (".codex/skills", "reflect")):
            (self.home / root / name).mkdir(parents=True)
            (self.home / root / name / "SKILL.md").write_text("x", encoding="utf-8")
        now = datetime.now(timezone.utc).isoformat()

        def used(harness: str, skill: str, source: str) -> dict[str, object]:
            return {"ts": now, "hook": "skill-usage-log", "harness": harness, "action": "skill_used",
                    "reason": source, "skill": skill, "rule_id": "", "mode_source": "stage"}

        self.write_events([used("claude", "diu", "skill_tool"), used("cursor", "diu", "read"), used("codex", "reflect", "mention")])
        result = self.run_report("--skills", "--since", "1d")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], "skill claude cursor codex sources")
        self.assertIn("diu 1 1 0 read=1,skill_tool=1", lines)
        self.assertIn("reflect 0 0 1 mention=1", lines)
        self.assertIn("idle no record", lines)

    def test_skills_report_exits_two_when_a_hook_run_could_not_read_its_input(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.write_events([{"ts": now, "hook": "skill-usage-log", "harness": "claude", "action": "skill_usage_unchecked", "reason": "bad_payload"}])
        result = self.run_report("--skills", "--since", "1d")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unchecked: 1 skill-usage-log run(s) could not read their input", result.stdout)

    def test_seeded_rows_include_no_record_and_unregistered(self) -> None:
        self.seed_configs()
        self.write_rows(
            [
                self.row("claude", "hook-a", "a.py", "crashed", exit_code=1, stderr_tail="boom\nsecond"),
                self.row("codex", "hook-c", "c.py", "silent", duration_ms=20),
                self.row("claude", "loose", "z.py", "timed_out", exit_code=1, stderr_tail="slow"),
            ],
            malformed=True,
        )
        result = self.run_report("--runs", "--since", "24h")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("skipped 1 malformed row(s)", result.stdout)
        self.assertIn("claude hook-a/a.py 1 0 0 0 1 0 0 10 boom", result.stdout)
        self.assertIn("cursor hook-b/b.py no record", result.stdout)
        self.assertIn("codex hook-c/c.py 1 0 1 0 0 0 0 20", result.stdout)
        self.assertIn("unregistered:\nclaude loose/z.py", result.stdout)

    def test_missing_log_exits_two_with_unchecked(self) -> None:
        self.seed_configs()
        result = self.run_report("--runs")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unchecked: no metrics log at", result.stdout)

    def test_json_output_reports_same_data(self) -> None:
        self.seed_configs()
        self.write_rows([self.row("claude", "hook-a", "a.py", "spoke")])
        result = self.run_report("--runs", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["registered"][0]["hook"], "hook-a")
        self.assertTrue(any(row["no_record"] for row in data["registered"]))

    def test_since_filters_old_rows(self) -> None:
        self.seed_configs()
        old = self.row("claude", "hook-a", "a.py", "spoke")
        old["ts"] = (datetime.now(timezone.utc) - timedelta(days=9)).isoformat()
        self.write_rows([old])
        result = self.run_report("--runs", "--since", "7d")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("claude hook-a/a.py no record", result.stdout)

    def test_event_report_suggests_each_mode_change(self) -> None:
        """Each suggestion needs a hook whose live registry entry can earn it.

        report.py reads the mode from engine/hooks/hooks.toml, not from the
        event rows, so "warn to stop" only appears for a hook the registry
        still records as warn with a why_mode of attention or outward.
        named-verb-guard sat here until its registry mode became stop."""
        rows: list[dict[str, object]] = []
        rows += self.closed_events(
            "claimed-search-not-run",
            "claimed.search",
            mode="warn",
            action="warned",
            outcomes=["acted"] * 30,
        )
        rows += self.closed_events(
            "repeat-error-stop",
            "repeat.error",
            mode="stop",
            action="stopped",
            outcomes=["acted"] * 26 + ["ignored"] * 4,
        )
        rows += self.closed_events(
            "restated-constraint",
            "restated.constraint",
            mode="warn",
            action="warned",
            outcomes=["ignored"] * 16 + ["acted"] * 14,
        )
        rows += self.closed_events(
            "hook-freshness",
            "freshness.behind",
            mode="warn",
            action="warned",
            outcomes=["acted"],
        )
        self.write_events(rows)

        result = self.run_report("--since", "24h")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "claimed-search-not-run claimed.search 30 0 30 30 0 0 0 0 29 0.00 warn to stop",
            result.stdout,
        )
        self.assertIn(
            "repeat-error-stop repeat.error 30 30 0 26 4 0 0 0 29 0.13 stop to warn",
            result.stdout,
        )
        self.assertIn(
            "restated-constraint restated.constraint 30 0 30 14 16 0 0 0 29 0.53 review or turn off",
            result.stdout,
        )
        self.assertIn(
            "hook-freshness freshness.behind 1 0 1 1 0 0 0 0 1 0.00 not enough data",
            result.stdout,
        )

    def test_event_report_unchecked_input_exits_two_but_prints_table(self) -> None:
        self.write_events(
            self.closed_events(
                "named-verb-guard",
                "named.proof",
                mode="warn",
                action="warned",
                outcomes=["acted"] * 30,
            ),
            malformed=True,
        )
        (self.metrics / "events-broken.jsonl").symlink_to(self.metrics / "missing.jsonl")
        (self.metrics / "fleet" / "offline-machine").mkdir(parents=True)

        result = self.run_report("--since", "24h")

        self.assertEqual(result.returncode, 2)
        self.assertIn("unchecked file:", result.stdout)
        self.assertIn("unchecked machine:", result.stdout)
        self.assertIn("skipped 1 malformed event row(s)", result.stdout)
        self.assertIn("named-verb-guard named.proof", result.stdout)


if __name__ == "__main__":
    unittest.main()
