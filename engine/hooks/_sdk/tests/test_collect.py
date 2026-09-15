from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


SDK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SDK_DIR))

import collect  # noqa: E402


class CollectTest(unittest.TestCase):
    def test_failed_machine_is_unchecked_and_other_machines_still_copy(self) -> None:
        calls: list[list[str]] = []

        def fake_runner(command: list[str]) -> None:
            calls.append(command)
            local_dir = Path(command[-1])
            if "bad@example.invalid" in command[-2]:
                raise RuntimeError("ssh: connection timed out")
            local_dir.mkdir(parents=True, exist_ok=True)
            (local_dir / "events-2026-09-15.jsonl").write_text('{"action":"warned"}\n', encoding="utf-8")

        targets = [
            collect.Target("bad", "example.invalid", "bad"),
            collect.Target("good", "example.test", "good"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            status = collect.collect(targets, fake_runner, Path(tmp), connect_timeout=7)
            saved_status = json.loads((Path(tmp) / "status.json").read_text(encoding="utf-8"))

            self.assertTrue((Path(tmp) / "good" / "events-2026-09-15.jsonl").exists())

        self.assertEqual(status, saved_status)
        self.assertEqual("unchecked", status["bad"]["status"])
        self.assertIn("connection timed out", status["bad"]["error"])
        self.assertEqual({"status": "ok"}, status["good"])
        self.assertEqual(2, len(calls))
        for command in calls:
            self.assertEqual("scp", command[0])
            self.assertIn("BatchMode=yes", command)
            self.assertIn("ConnectTimeout=7", command)
            self.assertTrue(command[-2].endswith(":~/.cache/catstack-hook-metrics/events-*.jsonl"))

    def test_main_uses_only_host_and_user_and_does_not_leak_config_secrets(self) -> None:
        secret_values = [
            "super-secret-password",
            "PRIVATE-KEY-CONTENTS",
            "do-not-print-token",
        ]
        config = {
            "remoteTargets": {
                "do1": {
                    "host": "example.test",
                    "user": "collector",
                    "password": secret_values[0],
                    "privateKey": secret_values[1],
                    "token": secret_values[2],
                },
                "do2": {
                    "host": "broken.test",
                    "user": "collector",
                    "password": "another-secret",
                },
            }
        }
        stdout = StringIO()
        stderr = StringIO()
        commands: list[list[str]] = []

        def fake_runner(command: list[str]) -> None:
            commands.append(command)
            if "broken.test" in command[-2]:
                raise RuntimeError("permission denied")
            Path(command[-1]).mkdir(parents=True, exist_ok=True)
            (Path(command[-1]) / "events-2026-09-15.jsonl").write_text("{}\n", encoding="utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            dest = Path(tmp) / "fleet"
            config_path.write_text(json.dumps(config), encoding="utf-8")

            with patch.object(collect, "default_runner", fake_runner):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    exit_code = collect.main(["--config", str(config_path), "--dest", str(dest)])

            status_text = (dest / "status.json").read_text(encoding="utf-8")

        self.assertEqual(1, exit_code)
        self.assertEqual("", stdout.getvalue())
        self.assertIn("catstack-hook-error collect: RuntimeError: permission denied", stderr.getvalue())
        self.assertEqual(2, len(commands))
        combined = stdout.getvalue() + stderr.getvalue() + status_text + json.dumps(commands)
        for secret in secret_values + ["another-secret"]:
            self.assertNotIn(secret, combined)
        self.assertIn('"status": "unchecked"', status_text)
        self.assertIn("permission denied", status_text)


if __name__ == "__main__":
    unittest.main()
