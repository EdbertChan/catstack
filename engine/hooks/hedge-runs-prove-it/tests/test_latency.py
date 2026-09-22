from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


HOOKS = Path(__file__).resolve().parents[2]
BUDGET_SECONDS = 5.0


class HookLatencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / ".git").mkdir()
        self.env = {
            "HOME": str(self.root),
            "PATH": os.environ.get("PATH", ""),
            "CATSTACK_HOOK_METRICS_DIR": str(self.root / "metrics"),
            "CATSTACK_LLM_JUDGE_STATE_DIR": str(self.root / "judge"),
            "CATSTACK_LLM_JUDGE_RUNNERS": "[]",
        }
        self.transcript = self.root / "session.jsonl"
        self.transcript.write_text("{}\n", encoding="utf-8")

    def invoke(self, script, payload, label, env=None):
        started = time.perf_counter()
        try:
            result = subprocess.run(
                [sys.executable, str(HOOKS / script)],
                input=json.dumps(payload), capture_output=True, text=True,
                env=self.env | (env or {}), cwd=self.root, timeout=BUDGET_SECONDS,
            )
        except subprocess.TimeoutExpired:
            self.fail(f"{label}: exceeded {BUDGET_SECONDS:.1f}s harness budget")
        elapsed = time.perf_counter() - started
        print(f"{label}: {elapsed:.3f}s exit={result.returncode}", flush=True)
        self.assertLess(elapsed, BUDGET_SECONDS, label)
        return result.returncode, result.stdout, result.stderr

    def write_results(self, results):
        entries = [{"type": "user", "message": {"content": "check the supported models"}}]
        entries.extend({"type": "user", "message": {
            "content": [{"type": "tool_result", "content": text}]
        }} for text in results)
        self.transcript.write_text("\n".join(map(json.dumps, entries)), encoding="utf-8")

    def test_capability_history_blocks_and_allows_under_five_seconds(self):
        values = [f"model-{i:04d}" for i in range(1500)]
        error = "Error: Known models: [" + ", ".join(values) + "]."
        padding = ["Build output: " + ("ordinary output " * 125) for _ in range(300)]
        payload = {
            "hook_event_name": "Stop", "session_id": "latency",
            "transcript_path": str(self.transcript),
            "last_assistant_message": "The tool supports [model-1498, model-1499].",
        }
        feedback = (
            "hedge-runs-prove-it: this reply asserts capability values copied only from "
            "error-shaped tool output (model-1498, model-1499). Verify them from a non-error source, or "
            "attribute them as an error, fallback, hardcoded, or built-in list."
        )
        for mode in ("stop", "warn", "off"):
            for supported in (False, True):
                label = f"hedge capability {mode} {'allow' if supported else 'hit'}"
                env = {"CATSTACK_HOOK_MODE_HEDGE_RUNS_PROVE_IT": mode}
                evidence = ["Supported models: [model-1498, model-1499]."] if supported else []
                self.write_results([error] + evidence)
                expected = self.invoke("hedge-runs-prove-it/claude_stop_check.py", payload, label + " compact", env)
                self.assertEqual(expected[0], 2 if mode == "stop" and not supported else 0)
                if supported or mode == "off":
                    self.assertEqual(expected, (0, "", ""))
                elif mode == "stop":
                    self.assertEqual(expected, (2, "", feedback + "\n"))
                else:
                    stdout = json.dumps({"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": feedback}}) + "\n"
                    self.assertEqual(expected, (0, stdout, ""))
                self.write_results([error] + padding + evidence)
                with self.subTest(mode=mode, supported=supported):
                    actual = self.invoke("hedge-runs-prove-it/claude_stop_check.py", payload, label + " history", env)
                    self.assertEqual(actual, expected)

    def test_cat_mode_fixture_responses_under_five_seconds(self):
        fixtures = HOOKS / "cat-mode-default/tests/fixtures"
        for path in sorted(fixtures.glob("*.json")):
            case = json.loads(path.read_text(encoding="utf-8"))
            payload = case["payload"] | {"cwd": str(self.root)}
            env = dict(case["environ"])
            env_file = self.root / ".env"
            env_file.unlink(missing_ok=True)
            if case.get("env_file") is not None:
                env_file.write_text(case["env_file"], encoding="utf-8")
            agent = path.name.startswith("agent_")
            script = "claude_pretooluse_agent.py" if agent else "claude_prompt_submit.py"
            result = self.invoke(f"cat-mode-default/{script}", payload, path.stem, env)
            context = "cat-mode default is on (CATSTACK_CAT_MODE_DEFAULT=on) but cat-mode is not installed: run install.sh."
            output = {"hookEventName": "UserPromptSubmit", "additionalContext": context}
            if agent:
                updated = payload["tool_input"] | {"prompt": context + "\n\n" + payload["tool_input"]["prompt"]}
                output = {"hookEventName": "PreToolUse", "updatedInput": updated}
            expected = json.dumps({"hookSpecificOutput": output}) + "\n" if case["expect"] == "fires" else ""
            self.assertEqual(result, (0, expected, ""))

    def test_scope_fixture_blocks_and_allows_under_five_seconds(self):
        self.transcript.write_text(json.dumps({"type": "user", "message": {
            "content": "can you make all tasks use claude and local executor"
        }}), encoding="utf-8")
        for name, code in (("update_tasks_status_in_pending_queued", 2), ("update_tasks_unfiltered", 0)):
            command = (HOOKS / f"categorical-scope-guard/tests/fixtures/{name}.txt").read_text(encoding="utf-8")
            result = self.invoke("categorical-scope-guard/claude_pretooluse.py", {
                "tool_name": "Bash", "tool_input": {"command": command},
                "transcript_path": str(self.transcript),
            }, name)
            self.assertEqual(result[:2], (code, ""))
            if code:
                self.assertIn("status in ('pending','queued')", result[2])
            else:
                self.assertEqual(result[2], "")

    def test_judge_inbox_hit_and_empty_under_five_seconds(self):
        digest = hashlib.sha1(str(self.transcript).encode()).hexdigest()[:16]
        folder = self.root / "judge/verdicts" / digest
        folder.mkdir(parents=True)
        for event, script in (("UserPromptSubmit", "claude_prompt_submit.py"), ("PostToolUse", "claude_post_tool_use.py")):
            (folder / "hit.json").write_text(json.dumps({
                "id": "hit", "hook": "demo-hook", "outcome": "hit", "on_hit": "judge hit text",
            }), encoding="utf-8")
            payload = {"transcript_path": str(self.transcript)}
            result = self.invoke(f"llm-judge/{script}", payload, f"judge {event} hit")
            expected = json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": "judge hit text"}}) + "\n"
            self.assertEqual(result, (0, expected, ""))
            result = self.invoke(f"llm-judge/{script}", payload, f"judge {event} empty")
            self.assertEqual(result, (0, "", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
