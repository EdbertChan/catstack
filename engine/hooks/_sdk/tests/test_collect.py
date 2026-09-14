from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SDK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SDK_DIR))

import collect


class FakeRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.timeouts: list[int] = []

    def __call__(self, command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        self.timeouts.append(timeout)
        destination = Path(command[-1].rstrip("/"))
        source = command[-2]
        if "down.example" in source:
            return subprocess.CompletedProcess(command, 255, "", "connection refused")
        (destination / "events-2026-09-14.jsonl").write_text('{"action":"warned"}\n', encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")


class CollectTest(unittest.TestCase):
    def test_collect_records_unchecked_failure_and_keeps_copying_other_machines(self) -> None:
        targets = [
            collect.Target("ok-machine", "ok.example", "invoker"),
            collect.Target("down-machine", "down.example", "invoker"),
        ]
        runner = FakeRunner()
        with tempfile.TemporaryDirectory() as tmp:
            status = collect.collect(targets, runner, Path(tmp))
            status_json = json.loads((Path(tmp) / "status.json").read_text(encoding="utf-8"))

            self.assertTrue((Path(tmp) / "ok-machine" / "events-2026-09-14.jsonl").exists())
            self.assertEqual("ok", status["ok-machine"]["status"])
            self.assertEqual("unchecked", status["down-machine"]["status"])
            self.assertEqual("connection refused", status["down-machine"]["error"])
            self.assertEqual(status, status_json["targets"])

        self.assertEqual(2, len(runner.commands))
        self.assertTrue(all("-o" in command for command in runner.commands))
        self.assertTrue(any("ConnectTimeout=8" in command for command in runner.commands))
        self.assertEqual([collect.COPY_TIMEOUT_SECONDS, collect.COPY_TIMEOUT_SECONDS], runner.timeouts)

    def test_main_reads_only_host_and_user_and_does_not_emit_config_secrets(self) -> None:
        config = {
            "remoteTargets": {
                "ok-machine": {
                    "host": "ok.example",
                    "user": "invoker",
                    "sshKeyPath": "/very/secret/key",
                    "token": "SUPER_SECRET_TOKEN",
                },
                "down-machine": {
                    "host": "down.example",
                    "user": "invoker",
                    "privateKey": "SUPER_SECRET_KEY",
                    "password": "SUPER_SECRET_PASSWORD",
                },
            }
        }
        runner = FakeRunner()
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            dest = Path(tmp) / "fleet"
            config_path.write_text(json.dumps(config), encoding="utf-8")

            with mock.patch.object(collect, "_subprocess_runner", runner), self._stdio():
                exit_code = collect.main(["--config", str(config_path), "--dest", str(dest)])
                stdout = sys.stdout.getvalue()
                stderr = sys.stderr.getvalue()

            status_text = (dest / "status.json").read_text(encoding="utf-8")

        self.assertEqual(1, exit_code)
        self.assertEqual("", stdout)
        self.assertIn("ok-machine: ok", stderr)
        self.assertIn("down-machine: unchecked: connection refused", stderr)
        for forbidden in ("/very/secret/key", "SUPER_SECRET_TOKEN", "SUPER_SECRET_KEY", "SUPER_SECRET_PASSWORD"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, stderr)
                self.assertNotIn(forbidden, status_text)
                self.assertNotIn(forbidden, json.dumps(runner.commands))

    @contextlib.contextmanager
    def _stdio(self):
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            yield
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr


if __name__ == "__main__":
    unittest.main()
