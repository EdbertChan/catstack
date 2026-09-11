import json
import os
import subprocess
import sys
import tempfile
import unittest

LIB_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, LIB_DIR)

import judge

PY = sys.executable
ON_HIT = "judge hit text"


class PostToolUseTestCase(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.TemporaryDirectory()
        self.work = tempfile.TemporaryDirectory()
        self.old_state = os.environ.get(judge.STATE_ENV)
        os.environ[judge.STATE_ENV] = self.state.name
        self.transcript = os.path.join(self.work.name, "session.jsonl")
        with open(self.transcript, "w", encoding="utf-8") as handle:
            handle.write("{}\n")

    def tearDown(self):
        if self.old_state is None:
            os.environ.pop(judge.STATE_ENV, None)
        else:
            os.environ[judge.STATE_ENV] = self.old_state
        self.state.cleanup()
        self.work.cleanup()

    def env(self):
        env = dict(os.environ)
        env[judge.STATE_ENV] = self.state.name
        return env

    def plant_hit(self):
        folder = judge.verdict_dir(self.transcript)
        os.makedirs(folder, exist_ok=True)
        judge.write_json_atomic(os.path.join(folder, "hit.json"), {
            "id": "hit",
            "hook": "demo-hook",
            "transcript": self.transcript,
            "outcome": "hit",
            "on_hit": ON_HIT,
            "reason": "all true: match",
            "finished_at": 1,
        })

    def run_script(self, script, stdin_text):
        return subprocess.run(
            [PY, os.path.join(LIB_DIR, script)],
            input=stdin_text,
            capture_output=True,
            text=True,
            timeout=10,
            env=self.env(),
        )

    def payload(self):
        return json.dumps({"transcript_path": self.transcript})


class TestClaudePostToolUse(PostToolUseTestCase):
    script = "claude_post_tool_use.py"
    harness = "Claude PostToolUse"

    def test_hit_is_delivered_as_additional_context_once(self):
        self.plant_hit()
        first = self.run_script(self.script, self.payload())
        self.assertEqual(first.returncode, 0)
        self.assertEqual(first.stderr, "")
        self.assertEqual(json.loads(first.stdout)["hookSpecificOutput"]["hookEventName"], "PostToolUse")
        self.assertEqual(json.loads(first.stdout)["hookSpecificOutput"]["additionalContext"], ON_HIT)
        second = self.run_script(self.script, self.payload())
        self.assertEqual(second.returncode, 0)
        self.assertEqual(second.stdout, "")

    def test_no_verdict_prints_nothing(self):
        result = self.run_script(self.script, self.payload())
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_malformed_stdin_exits_zero_with_stderr(self):
        result = self.run_script(self.script, "not json")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn(self.harness, result.stderr)


class TestCodexPostToolUse(TestClaudePostToolUse):
    script = "codex_post_tool_use.py"
    harness = "Codex PostToolUse"


class TestCursorPostToolUse(PostToolUseTestCase):
    script = "cursor_post_tool_use.py"
    harness = "Cursor postToolUse"

    def test_hit_is_delivered_as_additional_context_once(self):
        self.plant_hit()
        first = self.run_script(self.script, self.payload())
        self.assertEqual(first.returncode, 0)
        self.assertEqual(first.stderr, "")
        self.assertEqual(json.loads(first.stdout), {"additional_context": ON_HIT})
        second = self.run_script(self.script, self.payload())
        self.assertEqual(second.returncode, 0)
        self.assertEqual(second.stdout, "")

    def test_no_verdict_prints_nothing(self):
        result = self.run_script(self.script, self.payload())
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_malformed_stdin_exits_zero_with_stderr(self):
        result = self.run_script(self.script, "not json")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn(self.harness, result.stderr)

    def test_conversation_id_without_transcript_exits_zero_with_stderr(self):
        result = self.run_script(self.script, json.dumps({"conversation_id": "missing-conversation"}))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn(self.harness, result.stderr)


if __name__ == "__main__":
    unittest.main()
