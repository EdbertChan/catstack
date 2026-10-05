from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parent / "replay_hook_payloads.py"


class ReplayHookPayloadsCLI(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.payload_dir = self.root / "payloads"
        self.payload_dir.mkdir()
        self.hook = self.root / "hook.py"
        self.hook.write_text(
            "import json\n"
            "import os\n"
            "import sys\n"
            "payload = sys.stdin.buffer.read().decode('utf-8')\n"
            "mode = sys.argv[1]\n"
            "with open(os.environ['CATSTACK_HOOK_FINDINGS_FILE'], 'w', encoding='utf-8') as handle:\n"
            "    json.dump(['fixture.rule'], handle)\n"
            "if mode == 'block':\n"
            "    print(json.dumps({'decision': 'block', 'reason': payload}))\n"
            "elif mode == 'exit2':\n"
            "    sys.stderr.write(payload + '\\n')\n"
            "    sys.exit(2)\n"
            "else:\n"
            "    print(json.dumps({'hookSpecificOutput': {'additionalContext': mode + ':' + payload}}))\n",
            encoding="utf-8",
        )

    def _payload(self, body: bytes = b'{"hello":"world"}') -> str:
        name = f"{hashlib.sha256(body).hexdigest()[:12]}-fixture.json"
        (self.payload_dir / name).write_bytes(body)
        return name

    def _command(self, mode: str) -> str:
        return f"{shlex.quote(sys.executable)} {shlex.quote(str(self.hook))} {shlex.quote(mode)}"

    def _run(self, fleet_mode: str, dispatcher_mode: str) -> subprocess.CompletedProcess[str]:
        report = self.root / "report.json"
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--payload-dir",
                str(self.payload_dir),
                "--fleet",
                f"fixture={self._command(fleet_mode)}",
                "--dispatcher",
                f"fixture={self._command(dispatcher_mode)}",
                "--report-json",
                str(report),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def test_matching_commands_emit_match_table_and_json_report(self) -> None:
        payload_name = self._payload()

        result = self._run("same", "same")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"{payload_name} fixture match 0 0 spoke spoke", result.stdout)
        with open(self.root / "report.json", encoding="utf-8") as handle:
            report = json.load(handle)
        self.assertTrue(report["match"])
        self.assertEqual(report["rows"][0]["detector"], "fixture")
        self.assertEqual(report["rows"][0]["fleet"]["findings"], ["fixture.rule"])

    def test_mismatching_context_returns_nonzero_and_marks_the_row(self) -> None:
        self._payload()

        result = self._run("fleet", "dispatcher")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("fixture mismatch 0 0 spoke spoke", result.stdout)
        with open(self.root / "report.json", encoding="utf-8") as handle:
            report = json.load(handle)
        self.assertFalse(report["match"])
        self.assertNotEqual(
            report["rows"][0]["fleet"]["context"],
            report["rows"][0]["dispatcher"]["context"],
        )


if __name__ == "__main__":
    unittest.main()
