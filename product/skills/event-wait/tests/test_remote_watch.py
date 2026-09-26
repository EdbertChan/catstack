#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
WATCHER = os.path.join(os.path.dirname(HERE), "scripts", "remote_watch.py")

FAKE_SSH = """#!/bin/bash
set -euo pipefail
shift
exec bash -c "$*"
"""


class RemoteWatchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.ssh = self.write("fake-ssh", FAKE_SSH, executable=True)

    def write(self, name: str, body: str, executable: bool = False) -> str:
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
        if executable:
            os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        return path

    def pidfile_owner(self, pidfile: str):
        try:
            with open(pidfile, encoding="utf-8") as handle:
                return json.load(handle).get("pid")
        except (FileNotFoundError, ValueError):
            return None

    def watch(self, remote_body: str, *extra: str, timeout: float = 20.0) -> tuple[int, list[dict], str]:
        remote = self.write("remote.sh", remote_body)
        proc = subprocess.run(
            [sys.executable, WATCHER, "--host", "box", "--remote-script", remote,
             "--ssh-bin", self.ssh, "--status-field", "status",
             "--terminal", "completed", "--terminal", "failed", *extra],
            capture_output=True, text=True, timeout=timeout,
        )
        records = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
        return proc.returncode, records, proc.stderr

    def test_empty_reading_is_unread(self) -> None:
        code, records, _ = self.watch("true\n", "--once")
        self.assertEqual(records[-1]["verdict"], "unread")
        self.assertEqual(records[-1]["reason"], "empty")
        self.assertNotEqual(code, 0)

    def test_unparseable_reading_is_unread(self) -> None:
        code, records, _ = self.watch("echo 'wf: unbound variable'\n", "--once")
        self.assertEqual(records[-1]["verdict"], "unread")
        self.assertEqual(records[-1]["reason"], "not_json")
        self.assertNotEqual(code, 0)

    def test_remote_failure_is_unread(self) -> None:
        code, records, _ = self.watch("set -u\necho \"$missing_var\"\n", "--once")
        self.assertEqual(records[-1]["verdict"], "unread")
        self.assertEqual(records[-1]["reason"], "remote_exit")
        self.assertNotEqual(code, 0)

    def test_missing_field_is_unread(self) -> None:
        code, records, _ = self.watch("echo '{\"other\": 1}'\n", "--once")
        self.assertEqual(records[-1]["verdict"], "unread")
        self.assertEqual(records[-1]["reason"], "missing_field")
        self.assertNotEqual(code, 0)

    def test_real_running_reading_reports_status(self) -> None:
        code, records, _ = self.watch("echo '{\"status\": \"running\"}'\n", "--once")
        self.assertEqual(records[-1], {"record": "reading", "verdict": "running", "status": "running"})
        self.assertEqual(code, 0)

    def test_real_terminal_reading_reports_terminal(self) -> None:
        code, records, _ = self.watch("echo '{\"status\": \"completed\"}'\n", "--once")
        self.assertEqual(records[-1]["verdict"], "terminal")
        self.assertEqual(records[-1]["status"], "completed")
        self.assertEqual(code, 0)

    def test_remote_script_expands_on_remote_side(self) -> None:
        body = "set -u\nwf=wf-1234\nprintf '{\"status\": \"completed\", \"tail\": \"%s\"}\\n' \"${wf: -2}\"\n"
        code, records, _ = self.watch(body, "--once")
        self.assertEqual(records[-1]["verdict"], "terminal")
        self.assertEqual(code, 0)

    def test_loop_on_empty_readings_never_reports_stall(self) -> None:
        code, records, _ = self.watch(
            "true\n", "--interval", "0.05", "--stall-seconds", "0", "--idle", "idle", "--max-unread", "5"
        )
        verdicts = [r["verdict"] for r in records]
        self.assertNotIn("stalled", verdicts)
        self.assertNotIn("terminal", verdicts)
        self.assertEqual(records[-1]["record"], "result")
        self.assertEqual(records[-1]["verdict"], "unread")
        self.assertEqual(code, 4)

    def test_loop_on_real_idle_readings_reports_stall(self) -> None:
        code, records, _ = self.watch(
            "echo '{\"status\": \"idle\"}'\n", "--interval", "0.05", "--stall-seconds", "0.2", "--idle", "idle"
        )
        self.assertEqual(records[-1]["record"], "result")
        self.assertEqual(records[-1]["verdict"], "stalled")
        self.assertEqual(records[-1]["status"], "idle")
        self.assertEqual(code, 3)

    def test_loop_ends_on_terminal(self) -> None:
        code, records, _ = self.watch("echo '{\"status\": \"failed\"}'\n", "--interval", "0.05")
        self.assertEqual(records[-1]["record"], "result")
        self.assertEqual(records[-1]["verdict"], "terminal")
        self.assertEqual(records[-1]["status"], "failed")
        self.assertEqual(code, 0)

    def test_new_watcher_stops_older_one_with_same_pidfile(self) -> None:
        pidfile = os.path.join(self.tmp, "watch.pid")
        remote = self.write("remote.sh", "echo '{\"status\": \"running\"}'\n")
        argv = [sys.executable, WATCHER, "--host", "box", "--remote-script", remote,
                "--ssh-bin", self.ssh, "--status-field", "status", "--terminal", "completed",
                "--interval", "0.1", "--pidfile", pidfile]
        older = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            end = time.monotonic() + 10
            while time.monotonic() < end and not os.path.exists(pidfile):
                time.sleep(0.02)
            self.assertTrue(os.path.exists(pidfile))
            newer = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                older.wait(timeout=10)
                self.assertIsNotNone(older.returncode)
                end = time.monotonic() + 10
                while time.monotonic() < end and self.pidfile_owner(pidfile) != newer.pid:
                    time.sleep(0.02)
                self.assertEqual(self.pidfile_owner(pidfile), newer.pid)
            finally:
                newer.terminate()
                newer.wait(timeout=10)
        finally:
            if older.poll() is None:
                older.kill()
                older.wait(timeout=10)

    def test_pidfile_naming_unrelated_process_is_left_alone(self) -> None:
        pidfile = os.path.join(self.tmp, "watch.pid")
        bystander = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            with open(pidfile, "w", encoding="utf-8") as handle:
                json.dump({"pid": bystander.pid, "started": "Thu Jan  1 00:00:00 1970"}, handle)
            code, records, _ = self.watch("echo '{\"status\": \"completed\"}'\n", "--interval", "0.05", "--pidfile", pidfile)
            self.assertEqual(code, 0)
            self.assertIsNone(bystander.poll())
        finally:
            bystander.kill()
            bystander.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
