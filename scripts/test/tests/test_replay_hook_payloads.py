from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "replay_hook_payloads.py"
REPO_ROOT = SCRIPT.parents[2]
DETECTOR = "fixture-detector"


def command(message: str) -> list[str]:
    body = (
        "import json,os,sys;"
        "payload=json.load(sys.stdin);"
        "json.dump(['fixture.rule'],open(os.environ['CATSTACK_HOOK_FINDINGS_FILE'],'w'));"
        "os.makedirs(os.environ['CATSTACK_HOOK_METRICS_DIR'],exist_ok=True);"
        "open(os.path.join(os.environ['CATSTACK_HOOK_METRICS_DIR'],'runs.jsonl'),'a').write('{}\\n');"
        f"print(json.dumps({{'hookSpecificOutput':{{'additionalContext':{message!r}}}}}))"
    )
    return [sys.executable, "-c", body]


class ReplayHookPayloads(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.payloads = self.root / "payloads"
        self.payloads.mkdir()
        (self.payloads / f"abc123-{DETECTOR}.json").write_text(
            json.dumps({"hook_event_name": "SubagentStop", "session_id": "s1"}), encoding="utf-8"
        )
        self.report = self.root / "report.json"
        self.live_metrics = self.root / "live-metrics"

    def _write_commands(self, name: str, detector_command: list[str]) -> Path:
        path = self.root / name
        path.write_text(json.dumps({DETECTOR: detector_command}), encoding="utf-8")
        return path

    def _run(self, fleet_command: list[str], dispatcher_command: list[str]) -> subprocess.CompletedProcess[str]:
        fleet = self._write_commands("fleet.json", fleet_command)
        dispatcher = self._write_commands("dispatcher.json", dispatcher_command)
        env = os.environ.copy()
        env["CATSTACK_HOOK_METRICS_DIR"] = str(self.live_metrics)
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                str(self.payloads),
                "--fleet",
                str(fleet),
                "--dispatcher",
                str(dispatcher),
                "--report",
                str(self.report),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )

    def test_matching_commands_emit_a_per_detector_match_report_in_scratch_state(self) -> None:
        result = self._run(command("same"), command("same"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("fixture-detector", result.stdout)
        self.assertIn("MATCH", result.stdout)
        report = json.loads(self.report.read_text(encoding="utf-8"))
        self.assertTrue(report["match"])
        [row] = report["detectors"]
        self.assertEqual((row["detector"], row["payloads"], row["match"]), (DETECTOR, 1, True))
        self.assertEqual(row["cases"][0]["fleet"]["findings"], ["fixture.rule"])
        self.assertFalse(self.live_metrics.exists())

    def test_different_verdicts_emit_mismatch_and_exit_nonzero(self) -> None:
        result = self._run(command("fleet"), command("dispatcher"))

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("MISMATCH", result.stdout)
        report = json.loads(self.report.read_text(encoding="utf-8"))
        self.assertFalse(report["match"])
        self.assertFalse(report["detectors"][0]["cases"][0]["match"])

    def test_real_subagent_stop_manifest_inventory_matches_on_fixture_payload(self) -> None:
        hooks_source = REPO_ROOT / "engine" / "hooks"
        installed_hooks = self.root / "installed" / ".claude" / "hooks"
        installed_hooks.mkdir(parents=True)
        for child in hooks_source.iterdir():
            os.symlink(child, installed_hooks / child.name, target_is_directory=child.is_dir())
        sys.path.insert(0, str(REPO_ROOT / "scripts" / "install"))
        try:
            import mirror_stop_hooks_to_subagent_stop as mirror

            manifests = [manifest for manifest in mirror.load_manifests() if manifest.dispatch]
        finally:
            sys.path.remove(str(REPO_ROOT / "scripts" / "install"))
            sys.modules.pop("mirror_stop_hooks_to_subagent_stop", None)
        fleet = {}
        dispatcher = {}
        payload = json.dumps(
            {
                "hook_event_name": "SubagentStop",
                "session_id": "fixture-session",
                "agent_id": "fixture-agent",
                "last_assistant_message": "fixture reply",
            }
        )
        for manifest in manifests:
            commands = [hook["command"] for entry in manifest.entries for hook in entry["hooks"]]
            self.assertEqual(len(commands), 1, (manifest.name, commands))
            match = re.fullmatch(r"python3 \$HOME/\.claude/hooks/([^/]+)/([^\s]+\.py)", commands[0])
            self.assertIsNotNone(match, commands[0])
            hook, script = match.groups()
            fleet[manifest.name] = [
                sys.executable,
                str(installed_hooks / "_runner" / "run.py"),
                "--timeout",
                "4",
                f"{hook}/{script}",
            ]
            dispatcher[manifest.name] = [
                sys.executable,
                str(installed_hooks / "_runner" / "dispatch.py"),
                "--event",
                "SubagentStop",
                "--timeout",
                "9",
                "--detector-timeout",
                "4",
                "--only",
                manifest.name,
            ]
            (self.payloads / f"fixture-{manifest.name}.json").write_text(payload, encoding="utf-8")
        fleet_path = self._write_commands("real-fleet.json", [])
        dispatcher_path = self._write_commands("real-dispatcher.json", [])
        fleet_path.write_text(json.dumps(fleet), encoding="utf-8")
        dispatcher_path.write_text(json.dumps(dispatcher), encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                str(self.payloads),
                "--fleet",
                str(fleet_path),
                "--dispatcher",
                str(dispatcher_path),
                "--report",
                str(self.report),
                "--timeout",
                "12",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=180,
        )

        self.assertTrue(manifests)
        report = json.loads(self.report.read_text(encoding="utf-8"))
        self.assertEqual(
            result.returncode,
            0,
            result.stdout + result.stderr + json.dumps([row for row in report["detectors"] if not row["match"]], indent=2),
        )
        self.assertTrue(report["match"])
        self.assertEqual(len(report["detectors"]), len(manifests))

        full_metrics = self.root / "full-dispatch-metrics"
        full_home = self.root / "full-dispatch-home"
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(full_home),
                "CATSTACK_HOOK_METRICS_DIR": str(full_metrics),
                "CATSTACK_HOOK_REMINDER_STATE_DIR": str(self.root / "full-reminders"),
                "REFLECT_ON_THRASH_STATE_DIR": str(self.root / "full-reflect"),
                "VERDICT_FLIP_WATCH_STATE_DIR": str(self.root / "full-verdict-flip"),
                "WRONG_CHECK_REFLECT_STATE_DIR": str(self.root / "full-wrong-check"),
                "CATSTACK_UNVERIFIED_TAG_CHECK_STATE_DIR": str(self.root / "full-unverified"),
                "CATSTACK_LLM_JUDGE_STATE_DIR": str(self.root / "full-judge"),
            }
        )
        env.pop("CATSTACK_HOOK_PAYLOAD_DIR", None)
        started = time.monotonic()
        full = subprocess.run(
            [
                sys.executable,
                str(installed_hooks / "_runner" / "dispatch.py"),
                "--event",
                "SubagentStop",
                "--timeout",
                "9",
                "--detector-timeout",
                "4",
            ],
            input=payload.encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            timeout=12,
        )
        elapsed = time.monotonic() - started
        self.assertEqual(full.returncode, 0, full.stderr.decode(errors="replace"))
        rows = [
            json.loads(line)
            for line in (full_metrics / "runs.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(len(rows), 18)
        self.assertEqual(sum(row["dispatch_mode"] == "in_process" for row in rows), 15)
        self.assertEqual(sum(row["dispatch_mode"] == "subprocess_fallback" for row in rows), 3)
        self.assertLess(elapsed, 10.5)


if __name__ == "__main__":
    unittest.main()
