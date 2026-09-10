#!/usr/bin/env python3
"""Tests for the invoker-db-guard PreToolUse hook.

Run: python3 -m unittest discover -s engine/hooks/invoker-db-guard/tests -v

Fixtures hold one command per shape: every write shape the guard must block
(with the replacement command its message has to name), every neighbour it
must leave alone, and every input it cannot classify, which must come back
as `unchecked` rather than clean. The two python-heredoc write fixtures and
the two read-only connects are real commands with the home directory and ids
replaced.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(HOOK_DIR, "tests", "fixtures")
ENTRYPOINT = os.path.join(HOOK_DIR, "claude_pretooluse_check.py")
sys.path.insert(0, HOOK_DIR)

import claude_pretooluse_check  # noqa: E402
import detect  # noqa: E402

ENV = {"HOME": "/home/u"}


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)


def payload(command):
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def message_for(command):
    return detect.decide(payload(command), env=ENV) or ""


def run_entrypoint(stdin_text):
    env = dict(os.environ, HOME="/home/u")
    return subprocess.run(
        [sys.executable, ENTRYPOINT], input=stdin_text, capture_output=True, text=True, env=env, timeout=30
    )


class FixtureTests(unittest.TestCase):
    def test_fire_fixtures_block_and_name_the_replacement(self):
        for case in load("commands_fire.json"):
            with self.subTest(case["label"]):
                outcome, _ = detect.classify(case["command"], ENV)
                self.assertEqual(outcome, detect.HIT)
                message = message_for(case["command"])
                self.assertIn("invoker-db-guard: blocked a direct write", message)
                for expected in case["expect"]:
                    self.assertIn(expected, message)

    def test_silent_fixtures_allow(self):
        for case in load("commands_silent.json"):
            with self.subTest(case["label"]):
                outcome, _ = detect.classify(case["command"], ENV)
                self.assertEqual(outcome, detect.CLEAN)
                self.assertEqual(message_for(case["command"]), "")

    def test_unchecked_fixtures_block_as_unchecked_never_clean(self):
        for case in load("commands_unchecked.json"):
            with self.subTest(case["label"]):
                outcome, _ = detect.classify(case["command"], ENV)
                self.assertEqual(outcome, detect.UNCHECKED)
                message = message_for(case["command"])
                self.assertIn("could not tell whether this command writes", message)
                self.assertIn(case["why"], message)
                self.assertIn("A guard that cannot check does not assume safe", message)


class TargetSpellingTests(unittest.TestCase):
    WRITE = "\"UPDATE tasks SET status='pending' WHERE id='wf-1/a'\""

    def test_every_spelling_of_the_path_fires(self):
        spellings = [
            "~/.invoker/invoker.db",
            "$HOME/.invoker/invoker.db",
            "${HOME}/.invoker/invoker.db",
            "\"$HOME\"/.invoker/invoker.db",
            "/home/u/.invoker/invoker.db",
            "'file:/home/u/.invoker/invoker.db'",
            "~/.invoker/invoker.db-wal",
            "~/.invoker/invoker.db-shm",
        ]
        for path in spellings:
            with self.subTest(path):
                self.assertEqual(detect.classify(f"sqlite3 {path} {self.WRITE}", ENV)[0], detect.HIT)

    def test_variable_assigned_earlier_fires_in_each_form(self):
        forms = [
            "DB=~/.invoker/invoker.db; sqlite3 $DB {w}",
            "export DB=\"$HOME/.invoker/invoker.db\" && sqlite3 \"$DB\" {w}",
            "DIR=$HOME/.invoker\nsqlite3 \"${{DIR}}/invoker.db\" {w}",
            "sqlite3 \"${{DB:-$HOME/.invoker/invoker.db}}\" {w}",
        ]
        for form in forms:
            command = form.format(w=self.WRITE)
            with self.subTest(command):
                self.assertEqual(detect.classify(command, ENV)[0], detect.HIT)

    def test_unrelated_paths_stay_silent(self):
        for path in ("/tmp/other.db", "~/.invoker/invoker.db.bak", "~/.invoker/myinvoker.db", ":memory:"):
            with self.subTest(path):
                self.assertEqual(detect.classify(f"sqlite3 {path} {self.WRITE}", ENV)[0], detect.CLEAN)


class IntentTests(unittest.TestCase):
    def test_status_write_names_retry_task_retry_and_resume(self):
        message = message_for("sqlite3 ~/.invoker/invoker.db \"UPDATE tasks SET status='pending', error=NULL WHERE id='t'\"")
        self.assertIn("tasks.status -> use one of:", message)
        for command in ("invoker-cli retry-task <taskId>", "invoker-cli retry <workflowId>", "invoker-cli resume <workflowId>"):
            self.assertIn(command, message)
        self.assertNotIn("No headless command covers", message)

    def test_workflow_delete_names_delete(self):
        message = message_for("sqlite3 ~/.invoker/invoker.db \"DELETE FROM workflows WHERE id='wf-1'\"")
        self.assertIn("invoker-cli delete <workflowId>", message)
        self.assertNotIn("No headless command covers", message)

    def test_each_routing_column_names_its_set_subcommand_marked_landing(self):
        cases = {
            "execution_agent": "invoker-cli set agent <taskId> <agent>",
            "pool_id": "invoker-cli set pool <taskId> <pool>",
            "pool_member_id": "invoker-cli set pool <taskId> <pool>",
            "runner_kind": "invoker-cli set executor <taskId> <executor>",
            "remote_target_id": "invoker-cli set executor <taskId> <executor>",
        }
        for column, command in cases.items():
            with self.subTest(column):
                message = message_for(f"sqlite3 ~/.invoker/invoker.db \"UPDATE tasks SET {column}='x' WHERE id='t'\"")
                self.assertIn(command, message)
                self.assertIn("`invoker-cli set` is landing, not shipped", message)
                self.assertIn("(landing)", message)

    def test_config_json_edit_of_execution_agent_names_set_agent(self):
        command = (
            "python3 - <<'PY'\nimport sqlite3, json\nc = sqlite3.connect('/home/u/.invoker/invoker.db')\n"
            "d = {}\nd['executionAgent'] = 'claude'\n"
            "c.execute('update tasks set config=? where id=?', (json.dumps(d), 't'))\nPY"
        )
        self.assertIn("invoker-cli set agent <taskId> <agent>", message_for(command))

    def test_uncovered_write_says_no_command_and_next_step_is_adding_one(self):
        message = message_for("sqlite3 ~/.invoker/invoker.db \"UPDATE workflows SET merge_mode='manual' WHERE id='wf-1'\"")
        self.assertIn("No headless command covers UPDATE workflows SET merge_mode", message)
        self.assertIn("the next step is adding that headless command", message)
        self.assertIn("instead of writing SQL", message)

    def test_block_message_is_never_only_a_generic_pointer(self):
        for case in load("commands_fire.json"):
            with self.subTest(case["label"]):
                message = message_for(case["command"])
                self.assertTrue(
                    "invoker-cli " in message or "No headless command covers" in message,
                    message,
                )


class FixRetriggerMatrixTests(unittest.TestCase):
    """The rewrite each block message suggests must not block by any path."""

    PAIRS = [
        (
            "sqlite3 ~/.invoker/invoker.db \"UPDATE tasks SET status='pending' WHERE id='wf-1/a'\"",
            "invoker-cli retry-task wf-1/a",
        ),
        (
            "sqlite3 ~/.invoker/invoker.db \"DELETE FROM workflows WHERE id='wf-1'\"",
            "invoker-cli delete wf-1",
        ),
        (
            "python3 -c \"import sqlite3; c=sqlite3.connect('/home/u/.invoker/invoker.db'); print(c.execute('select 1').fetchone())\"",
            "python3 -c \"import sqlite3; c=sqlite3.connect('file:/home/u/.invoker/invoker.db?mode=ro', uri=True); print(c.execute('select 1').fetchone())\"",
        ),
        (
            "sqlite3 ~/.invoker/invoker.db < /tmp/report.sql",
            "sqlite3 -readonly ~/.invoker/invoker.db < /tmp/report.sql",
        ),
        (
            "sqlite3 ~/.invoker/invoker.db < /tmp/report.sql",
            "sqlite3 ~/.invoker/invoker.db \"SELECT id, status FROM tasks\"",
        ),
    ]

    def test_broken_blocks_and_fixed_passes(self):
        for broken, fixed in self.PAIRS:
            with self.subTest(broken):
                self.assertNotEqual(detect.classify(broken, ENV)[0], detect.CLEAN)
                self.assertEqual(detect.classify(fixed, ENV)[0], detect.CLEAN)


class EveryStageTests(unittest.TestCase):
    def test_hit_in_a_late_stage_still_fires(self):
        command = (
            "ls ~/.invoker\nsqlite3 ~/.invoker/invoker.db 'SELECT 1'\n"
            "echo ok && sqlite3 ~/.invoker/invoker.db \"UPDATE tasks SET status='pending'\""
        )
        self.assertEqual(detect.classify(command, ENV)[0], detect.HIT)

    def test_hit_outranks_unchecked_and_both_are_reported(self):
        command = "sqlite3 ~/.invoker/invoker.db < /tmp/a.sql; sqlite3 ~/.invoker/invoker.db \"DELETE FROM workflows WHERE id='w'\""
        outcome, verdicts = detect.classify(command, ENV)
        self.assertEqual(outcome, detect.HIT)
        self.assertEqual(sorted(v.outcome for v in verdicts), [detect.HIT, detect.UNCHECKED])

    def test_writes_in_command_substitution_and_process_substitution_fire(self):
        for command in (
            "echo \"$(sqlite3 ~/.invoker/invoker.db \"DELETE FROM workflows WHERE id='w'\")\"",
            "diff <(sqlite3 ~/.invoker/invoker.db \"DELETE FROM workflows WHERE id='w'\") /dev/null",
            "echo `sqlite3 ~/.invoker/invoker.db 'DROP TABLE tasks'`",
        ):
            with self.subTest(command):
                self.assertEqual(detect.classify(command, ENV)[0], detect.HIT)

    def test_deep_shell_nesting_does_not_crash_and_is_not_flagged(self):
        command = "bash -c " * 12 + "true"
        self.assertEqual(detect.classify(command, ENV)[0], detect.CLEAN)


class EntrypointTests(unittest.TestCase):
    def test_entrypoint_blocks_a_write_with_exit_2(self):
        result = run_entrypoint(json.dumps(payload("sqlite3 ~/.invoker/invoker.db \"UPDATE tasks SET status='pending'\"")))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("invoker-cli retry-task <taskId>", result.stderr)

    def test_entrypoint_blocks_unchecked_with_exit_2(self):
        result = run_entrypoint(json.dumps(payload("sqlite3 ~/.invoker/invoker.db < /tmp/fix.sql")))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("could not tell whether this command writes", result.stderr)

    def test_entrypoint_allows_a_read_silently(self):
        result = run_entrypoint(json.dumps(payload("sqlite3 ~/.invoker/invoker.db 'SELECT count(*) FROM tasks'")))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")

    def test_malformed_payload_fails_open_and_says_unchecked(self):
        result = run_entrypoint("{not json")
        self.assertEqual(result.returncode, 0)
        self.assertIn("this call was not checked", result.stderr)

    def test_non_object_payload_fails_open_and_says_unchecked(self):
        result = run_entrypoint("[1, 2]")
        self.assertEqual(result.returncode, 0)
        self.assertIn("this call was not checked", result.stderr)

    def test_detector_error_fails_open_and_says_unchecked(self):
        err = io.StringIO()
        stdin = io.StringIO(json.dumps(payload("sqlite3 ~/.invoker/invoker.db 'DROP TABLE tasks'")))
        with patch.object(sys, "stdin", stdin), patch.object(claude_pretooluse_check, "decide", side_effect=RuntimeError("boom")):
            with redirect_stderr(err):
                claude_pretooluse_check.main()
        self.assertIn("detector error, this call was not checked and is allowed", err.getvalue())
        self.assertIn("boom", err.getvalue())

    def test_missing_command_is_silent(self):
        self.assertIsNone(detect.decide({"tool_name": "Bash", "tool_input": {}}, env=ENV))
        self.assertIsNone(detect.decide({"tool_name": "Bash", "tool_input": "x"}, env=ENV))


if __name__ == "__main__":
    unittest.main()
