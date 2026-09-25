from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class DispatchCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home")
        self.hooks_root = os.path.join(self.home, ".claude", "hooks")
        self.runner_dir = os.path.join(self.hooks_root, "_runner")
        self.metrics_dir = os.path.join(self.tmp.name, "metrics")
        os.makedirs(self.runner_dir)
        for name in ("run.py", "outcome.py", "dispatch.py"):
            shutil.copy2(os.path.join(RUNNER_DIR, name), os.path.join(self.runner_dir, name))

    def _write_hook(self, name: str, script: str, body: str, event: str = "PreToolUse", matcher=None) -> None:
        hook_dir = os.path.join(self.hooks_root, name)
        os.makedirs(hook_dir)
        with open(os.path.join(hook_dir, script), "w", encoding="utf-8") as handle:
            handle.write(body)
        entry = {"hooks": [{"type": "command", "command": f"python3 $HOME/.claude/hooks/{name}/{script}"}]}
        if matcher is not None:
            entry["matcher"] = matcher
        manifest = {"hooks": {event: [entry]}}
        with open(os.path.join(hook_dir, "claude.hook.json"), "w", encoding="utf-8") as handle:
            json.dump(manifest, handle)

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["HOME"] = self.home
        env["CATSTACK_HOOK_METRICS_DIR"] = self.metrics_dir
        return env

    def _stdin(self, tool_name: str | None = None) -> bytes:
        payload = {"hook_event_name": "PreToolUse", "session_id": "s1"}
        if tool_name is not None:
            payload["tool_name"] = tool_name
        return json.dumps(payload).encode()

    def _run(self, event: str = "PreToolUse", timeout: str = "5", tool_name: str | None = None) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [sys.executable, os.path.join(self.runner_dir, "dispatch.py"), "--event", event, "--timeout", timeout],
            input=self._stdin(tool_name),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._env(),
        )

    def _rows(self) -> list[dict[str, object]]:
        path = os.path.join(self.metrics_dir, "runs.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle]

    def _row_for(self, hook: str) -> dict[str, object]:
        matches = [row for row in self._rows() if row["hook"] == hook]
        self.assertEqual(len(matches), 1, matches)
        return matches[0]

    def test_a_raising_hook_gets_its_own_crashed_row_while_a_sibling_still_speaks(self):
        self._write_hook(
            "fixture-ok",
            "ok.py",
            "import json\nprint(json.dumps({'hookSpecificOutput': {'additionalContext': 'hi from ok'}}))\n",
        )
        self._write_hook("fixture-crash", "crash.py", "raise RuntimeError('boom')\n")

        result = self._run()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"hi from ok", result.stdout)
        ok_row = self._row_for("fixture-ok")
        self.assertEqual(ok_row["outcome"], "spoke")
        crash_row = self._row_for("fixture-crash")
        self.assertEqual(crash_row["outcome"], "crashed")
        self.assertNotEqual(crash_row["exit_code"], 0)

    def test_a_hanging_hook_gets_its_own_timed_out_row_while_a_sibling_still_speaks(self):
        self._write_hook(
            "fixture-ok",
            "ok.py",
            "import json\nprint(json.dumps({'hookSpecificOutput': {'additionalContext': 'hi from ok'}}))\n",
        )
        self._write_hook("fixture-slow", "slow.py", "import time\ntime.sleep(30)\n")

        result = self._run(timeout="1")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"hi from ok", result.stdout)
        ok_row = self._row_for("fixture-ok")
        self.assertEqual(ok_row["outcome"], "spoke")
        slow_row = self._row_for("fixture-slow")
        self.assertEqual(slow_row["outcome"], "timed_out")
        self.assertIn(b"fixture-slow/slow.py timed out after 1", result.stderr)

    def test_raising_and_hanging_siblings_each_get_their_own_row_in_the_same_dispatch(self):
        self._write_hook(
            "fixture-ok",
            "ok.py",
            "import json\nprint(json.dumps({'hookSpecificOutput': {'additionalContext': 'hi from ok'}}))\n",
        )
        self._write_hook("fixture-crash", "crash.py", "raise RuntimeError('boom')\n")
        self._write_hook("fixture-slow", "slow.py", "import time\ntime.sleep(30)\n")

        result = self._run(timeout="3")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"hi from ok", result.stdout)
        rows = {row["hook"]: row for row in self._rows()}
        self.assertEqual(set(rows), {"fixture-ok", "fixture-crash", "fixture-slow"})
        self.assertEqual(rows["fixture-ok"]["outcome"], "spoke")
        self.assertEqual(rows["fixture-crash"]["outcome"], "crashed")
        self.assertEqual(rows["fixture-slow"]["outcome"], "timed_out")

    def test_a_blocking_hook_wins_over_a_speaking_sibling(self):
        self._write_hook(
            "fixture-ok",
            "ok.py",
            "import json\nprint(json.dumps({'hookSpecificOutput': {'additionalContext': 'hi from ok'}}))\n",
        )
        self._write_hook(
            "fixture-block",
            "block.py",
            "import sys\nsys.stderr.write('nope\\n')\nsys.exit(2)\n",
        )

        result = self._run()

        self.assertEqual(result.returncode, 2, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["decision"], "block")
        self.assertEqual(rows_outcome(self._rows(), "fixture-block"), "blocked")

    def test_no_hooks_registered_for_the_event_is_a_quiet_success(self):
        self._write_hook("fixture-ok", "ok.py", "print('should not run')\n", event="Stop")

        result = self._run(event="PreToolUse")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(self._rows(), [])

    def test_matcher_on_the_manifest_filters_which_hooks_run(self):
        self._write_hook(
            "fixture-bash",
            "bash.py",
            "import json\nprint(json.dumps({'hookSpecificOutput': {'additionalContext': 'bash ran'}}))\n",
            matcher="Bash",
        )
        self._write_hook(
            "fixture-write",
            "write.py",
            "import json\nprint(json.dumps({'hookSpecificOutput': {'additionalContext': 'write ran'}}))\n",
            matcher="Write",
        )

        result = self._run(tool_name="Bash")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"bash ran", result.stdout)
        self.assertNotIn(b"write ran", result.stdout)
        self.assertEqual(rows_outcome(self._rows(), "fixture-bash"), "spoke")
        self.assertEqual(self._rows(), [row for row in self._rows() if row["hook"] == "fixture-bash"])


def rows_outcome(rows: list[dict[str, object]], hook: str) -> str:
    matches = [row["outcome"] for row in rows if row["hook"] == hook]
    assert len(matches) == 1, matches
    return matches[0]


if __name__ == "__main__":
    unittest.main()
