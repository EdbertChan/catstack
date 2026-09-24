from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class RunnerCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home")
        self.hooks_root = os.path.join(self.home, ".claude", "hooks")
        self.runner_dir = os.path.join(self.hooks_root, "_runner")
        self.fixture_dir = os.path.join(self.hooks_root, "fixture")
        self.metrics_dir = os.path.join(self.tmp.name, "metrics")
        os.makedirs(self.runner_dir)
        os.makedirs(self.fixture_dir)
        shutil.copy2(os.path.join(RUNNER_DIR, "run.py"), os.path.join(self.runner_dir, "run.py"))
        shutil.copy2(os.path.join(RUNNER_DIR, "outcome.py"), os.path.join(self.runner_dir, "outcome.py"))
        self._write_fixture("silent.py", "")
        self._write_fixture("spoke.py", "import json\nprint(json.dumps({'hookSpecificOutput': {'additionalContext': 'hi'}}))\n")
        self._write_fixture("block_exit2.py", "import sys\nsys.stderr.write('blocked\\n')\nsys.exit(2)\n")
        self._write_fixture("block_json.py", "print('{\"decision\":\"block\",\"reason\":\"x\"}')\n")
        self._write_fixture("crash.py", "raise RuntimeError('boom')\n")
        self._write_fixture("slow.py", "import time\ntime.sleep(5)\n")
        self._write_fixture("caught.py", "import sys\nsys.stderr.write('catstack-hook-error fixture: ValueError: x\\n')\n")
        self._write_fixture(
            "findings.py",
            "import json\nimport os\n"
            "with open(os.environ['CATSTACK_HOOK_FINDINGS_FILE'], 'w', encoding='utf-8') as handle:\n"
            "    json.dump(['fixture.first', 'fixture.second'], handle)\n",
        )

    def _write_fixture(self, name: str, body: str) -> None:
        with open(os.path.join(self.fixture_dir, name), "w", encoding="utf-8") as handle:
            handle.write(body)

    def _env(self, metrics_dir: str | None = None) -> dict[str, str]:
        env = os.environ.copy()
        env["CATSTACK_HOOK_METRICS_DIR"] = self.metrics_dir if metrics_dir is None else metrics_dir
        return env

    def _stdin(self) -> bytes:
        return json.dumps({"hook_event_name": "PromptSubmit", "session_id": "s1"}).encode()

    def _direct(self, script: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [sys.executable, os.path.join(self.fixture_dir, script)],
            input=self._stdin(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._env(),
        )

    def _runner(self, script: str, *args: str, metrics_dir: str | None = None) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [sys.executable, os.path.join(self.runner_dir, "run.py"), *args, f"fixture/{script}"],
            input=self._stdin(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._env(metrics_dir),
        )

    def _row(self) -> dict[str, object]:
        with open(os.path.join(self.metrics_dir, "runs.jsonl"), encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle]
        self.assertEqual(len(rows), 1)
        return rows[0]

    def test_recording_failure_still_forwards_hook_result(self) -> None:
        with open(os.path.join(self.runner_dir, "outcome.py"), "w", encoding="utf-8") as handle:
            handle.write("def classify(*args, **kwargs):\n    raise RuntimeError('classify broke')\n")
        direct = self._direct("spoke.py")
        wrapped = self._runner("spoke.py")
        self.assertEqual(wrapped.stdout, direct.stdout)
        self.assertEqual(wrapped.returncode, direct.returncode)
        self.assertIn(b"catstack-hook-metrics: could not record run: RuntimeError: classify broke", wrapped.stderr)

    def _assert_run_matches_direct(self, script: str, outcome: str) -> None:
        direct = self._direct(script)
        wrapped = self._runner(script)
        self.assertEqual(wrapped.stdout, direct.stdout)
        self.assertEqual(wrapped.stderr, direct.stderr)
        self.assertEqual(wrapped.returncode, direct.returncode)
        row = self._row()
        self.assertEqual(row["outcome"], outcome)
        self.assertEqual(row["harness"], "claude")
        self.assertEqual(row["hook"], "fixture")
        self.assertEqual(row["script"], script)
        self.assertEqual(row["event"], "PromptSubmit")
        self.assertEqual(row["session_id"], "s1")
        self.assertEqual(row["exit_code"], direct.returncode)
        self.assertEqual(row["rule_ids"], [])
        self.assertEqual(row["stdout_bytes"], len(direct.stdout))

    def test_notify_mode_reads_the_payload_argument_not_stdin(self):
        argv_out = os.path.join(self.tmp.name, "argv.json")
        self._write_fixture("notify.py", f"import json, sys\njson.dump(sys.argv[1:], open({argv_out!r}, 'w'))\n")
        payload = json.dumps({"type": "agent-turn-complete", "thread-id": "t-1", "last-assistant-message": "ok"})
        proc = subprocess.Popen(
            [sys.executable, os.path.join(self.runner_dir, "run.py"), "--notify", "--timeout", "9",
             "fixture/notify.py", "next-in-chain", payload],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._env(),
        )
        self.assertEqual(proc.wait(timeout=10), 0, "runner waited on stdin in notify mode")
        proc.stdin.close()
        proc.stdout.close()
        proc.stderr.close()
        with open(argv_out, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), ["next-in-chain", payload])
        row = self._row()
        self.assertEqual((row["event"], row["session_id"], row["outcome"]), ("agent-turn-complete", "t-1", "silent"))

    def test_silent_hook_stays_silent(self):
        self._assert_run_matches_direct("silent.py", "silent")

    def test_spoke_hook_keeps_stdout_bytes(self):
        self._assert_run_matches_direct("spoke.py", "spoke")

    def test_exit_two_hook_blocks(self):
        self._assert_run_matches_direct("block_exit2.py", "blocked")

    def test_block_json_hook_blocks(self):
        self._assert_run_matches_direct("block_json.py", "blocked")

    def test_crash_hook_crashes(self):
        self._assert_run_matches_direct("crash.py", "crashed")

    def test_caught_error_hook_is_caught(self):
        self._assert_run_matches_direct("caught.py", "caught_error")

    def test_findings_file_rule_ids_are_recorded(self):
        wrapped = self._runner("findings.py")
        self.assertEqual(wrapped.stdout, b"")
        self.assertEqual(wrapped.stderr, b"")
        self.assertEqual(wrapped.returncode, 0)
        row = self._row()
        self.assertEqual(row["outcome"], "silent")
        self.assertEqual(row["rule_ids"], ["fixture.first", "fixture.second"])

    def test_slow_hook_times_out(self):
        wrapped = self._runner("slow.py", "--timeout", "1")
        self.assertEqual(wrapped.stdout, b"")
        self.assertIn(b"catstack-hook-runner: fixture/slow.py timed out after 1s\n", wrapped.stderr)
        self.assertEqual(wrapped.returncode, 1)
        row = self._row()
        self.assertEqual(row["outcome"], "timed_out")
        self.assertEqual(row["harness"], "claude")
        self.assertEqual(row["hook"], "fixture")
        self.assertEqual(row["script"], "slow.py")
        self.assertEqual(row["event"], "PromptSubmit")
        self.assertEqual(row["exit_code"], 1)
        self.assertEqual(row["rule_ids"], [])

    def test_missing_hook_script_records_crash(self):
        wrapped = self._runner("missing.py")
        self.assertEqual(wrapped.stdout, b"")
        self.assertEqual(wrapped.returncode, 1)
        self.assertIn(b"catstack-hook-runner: no such hook script:", wrapped.stderr)
        row = self._row()
        self.assertEqual(row["outcome"], "crashed")
        self.assertEqual(row["hook"], "fixture")
        self.assertEqual(row["script"], "missing.py")
        self.assertEqual(row["exit_code"], 1)
        self.assertEqual(row["rule_ids"], [])

    def test_metrics_write_failure_adds_one_stderr_line(self):
        direct = self._direct("spoke.py")
        metrics_file = os.path.join(self.tmp.name, "metrics-file")
        with open(metrics_file, "w", encoding="utf-8") as handle:
            handle.write("")
        wrapped = self._runner("spoke.py", metrics_dir=metrics_file)
        self.assertEqual(wrapped.stdout, direct.stdout)
        self.assertEqual(wrapped.returncode, direct.returncode)
        self.assertEqual(direct.stderr, b"")
        self.assertIn(b"catstack-hook-metrics: could not write row", wrapped.stderr)
        self.assertEqual(len([line for line in wrapped.stderr.splitlines() if line]), 1)

    def test_non_json_stdin_records_null_event_and_conversation_id_fallback(self):
        wrapped = subprocess.run(
            [sys.executable, os.path.join(self.runner_dir, "run.py"), "fixture/silent.py"],
            input=b"not json",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._env(),
        )
        self.assertEqual(wrapped.returncode, 0)
        row = self._row()
        self.assertIsNone(row["event"])
        self.assertIsNone(row["session_id"])

    def test_conversation_id_records_session_id_when_session_id_absent(self):
        wrapped = subprocess.run(
            [sys.executable, os.path.join(self.runner_dir, "run.py"), "fixture/silent.py"],
            input=json.dumps({"hook_event_name": "Stop", "conversation_id": "c1"}).encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._env(),
        )
        self.assertEqual(wrapped.returncode, 0)
        row = self._row()
        self.assertEqual(row["event"], "Stop")
        self.assertEqual(row["session_id"], "c1")

    def _rotated_env(self, max_bytes: int, keep: int) -> dict[str, str]:
        env = self._env()
        env["CATSTACK_HOOK_METRICS_MAX_BYTES"] = str(max_bytes)
        env["CATSTACK_HOOK_METRICS_KEEP"] = str(keep)
        return env

    def _run_with(self, env: dict[str, str], session: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [sys.executable, os.path.join(self.runner_dir, "run.py"), "fixture/silent.py"],
            input=json.dumps({"hook_event_name": "PromptSubmit", "session_id": session}).encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )

    def _sessions(self, name: str) -> list[str]:
        with open(os.path.join(self.metrics_dir, name), encoding="utf-8") as handle:
            return [json.loads(line)["session_id"] for line in handle]

    def test_log_past_the_cap_rotates_and_keeps_at_most_keep_files(self):
        env = self._rotated_env(max_bytes=200, keep=2)
        written = []
        for index in range(12):
            session = f"s{index}"
            result = self._run_with(env, session)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, b"")
            written.append(session)
            self.assertEqual(self._sessions("runs.jsonl")[-1], session)
            names = sorted(os.listdir(self.metrics_dir))
            self.assertLessEqual(len([name for name in names if name.startswith("runs.jsonl.")]), 2, names)
        self.assertEqual(sorted(os.listdir(self.metrics_dir)), ["runs.jsonl", "runs.jsonl.1", "runs.jsonl.2"])
        kept = self._sessions("runs.jsonl.2") + self._sessions("runs.jsonl.1") + self._sessions("runs.jsonl")
        self.assertEqual(kept, written[-len(kept):])
        self.assertLess(len(kept), len(written))

    def test_log_under_the_cap_is_not_rotated(self):
        env = self._rotated_env(max_bytes=1_000_000, keep=2)
        for index in range(3):
            self.assertEqual(self._run_with(env, f"s{index}").returncode, 0)
        self.assertEqual(os.listdir(self.metrics_dir), ["runs.jsonl"])
        self.assertEqual(self._sessions("runs.jsonl"), ["s0", "s1", "s2"])

    def test_rotation_failure_reports_on_stderr_and_still_writes_the_row(self):
        env = self._rotated_env(max_bytes=1, keep=1)
        self.assertEqual(self._run_with(env, "s0").returncode, 0)
        blocker = os.path.join(self.metrics_dir, "runs.jsonl.1")
        os.makedirs(os.path.join(blocker, "inside"))
        result = self._run_with(env, "s1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"catstack-hook-metrics: could not rotate", result.stderr)
        self.assertEqual(self._sessions("runs.jsonl"), ["s0", "s1"])

    def test_invalid_rotation_settings_are_reported_and_fall_back_to_defaults(self):
        env = self._env()
        env["CATSTACK_HOOK_METRICS_MAX_BYTES"] = "lots"
        env["CATSTACK_HOOK_METRICS_KEEP"] = "0"
        result = self._run_with(env, "s0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"catstack-hook-metrics: ignoring CATSTACK_HOOK_METRICS_MAX_BYTES='lots'", result.stderr)
        self.assertIn(b"catstack-hook-metrics: ignoring CATSTACK_HOOK_METRICS_KEEP='0'", result.stderr)
        self.assertEqual(self._sessions("runs.jsonl"), ["s0"])


if __name__ == "__main__":
    unittest.main()
