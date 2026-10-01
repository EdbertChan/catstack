from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "test" / "replay_hook_payloads.py"


class ReplayHookPayloads(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.payload_dir = self.root / "payloads"
        self.payload_dir.mkdir()
        self.payload = json.dumps({"hook_event_name": "PromptSubmit", "session_id": "s1"}).encode()
        self.event_uid = hashlib.sha256(self.payload).hexdigest()[:12]
        (self.payload_dir / f"{self.event_uid}-fixture.json").write_bytes(self.payload)

    def _hook(self, name: str, body: str) -> Path:
        path = self.root / name
        path.write_text(body, encoding="utf-8")
        return path

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--payload-dir", str(self.payload_dir), *args],
            capture_output=True,
            text=True,
            cwd=REPO,
        )

    def test_matching_commands_emit_json_report_and_table(self) -> None:
        hook = self._hook(
            "matching_hook.py",
            "import json, os\n"
            "with open(os.environ['CATSTACK_HOOK_FINDINGS_FILE'], 'w', encoding='utf-8') as handle:\n"
            "    json.dump(['fixture.rule'], handle)\n"
            "print(json.dumps({'hookSpecificOutput': {'additionalContext': 'same'}}))\n",
        )
        report_path = self.root / "report.json"
        command = f"{sys.executable} {hook}"
        result = self._run(
            "--fleet",
            f"fixture={command}",
            "--dispatcher",
            f"fixture={command}",
            "--json-out",
            str(report_path),
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("fixture", result.stdout)
        self.assertIn("match", result.stdout)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertTrue(report["match"])
        self.assertEqual(report["rows"][0]["fleet"]["context"], "same")
        self.assertEqual(report["rows"][0]["dispatcher"]["findings"], ["fixture.rule"])

    def test_mismatch_reports_the_different_verdict_fields(self) -> None:
        fleet = self._hook("fleet.py", "print('ok')\n")
        dispatcher = self._hook("dispatcher.py", "import sys\nsys.exit(2)\n")
        result = self._run(
            "--fleet",
            f"fixture={sys.executable} {fleet}",
            "--dispatcher",
            f"fixture={sys.executable} {dispatcher}",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("mismatch", result.stdout)
        self.assertIn("diff", result.stdout)

    def test_replay_uses_scratch_metrics_and_home(self) -> None:
        live_metrics = self.root / "live-metrics"
        live_metrics.mkdir()
        env_script = self._hook(
            "env_hook.py",
            "import os, pathlib\n"
            "metrics = pathlib.Path(os.environ['CATSTACK_HOOK_METRICS_DIR'])\n"
            "metrics.mkdir(parents=True, exist_ok=True)\n"
            "(metrics / 'runs.jsonl').write_text('scratch', encoding='utf-8')\n"
            "assert str(pathlib.Path.home()).startswith(os.environ['TMPDIR'].rsplit('/tmp', 1)[0])\n",
        )
        command = f"{sys.executable} {env_script}"
        env = os.environ.copy()
        env["CATSTACK_HOOK_METRICS_DIR"] = str(live_metrics)
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--payload-dir",
                str(self.payload_dir),
                "--fleet",
                f"fixture={command}",
                "--dispatcher",
                f"fixture={command}",
            ],
            capture_output=True,
            text=True,
            cwd=REPO,
            env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertFalse((live_metrics / "runs.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
