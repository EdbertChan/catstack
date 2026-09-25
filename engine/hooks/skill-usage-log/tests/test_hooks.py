#!/usr/bin/env python3
"""Tests for skill-usage-log.

Run: python3 -m unittest discover -s engine/hooks/skill-usage-log/tests -v
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOKS_DIR)

import detect  # noqa: E402
import log  # noqa: E402

HOME = "/Users/someone"
CODEX_EXEC = (
    "const r = await tools.exec_command({cmd:\"sed -n '1,240p' "
    f"{HOME}/.codex/skills/invoker-make-pr/SKILL.md && pwd\"}});"
)


def tool(name, tool_input):
    return {"hook_event_name": "PreToolUse", "session_id": "s-1", "tool_name": name, "tool_input": tool_input}


class TestToolUses(unittest.TestCase):
    def test_detects_real_shapes_from_each_harness_as_uses(self):
        cases = [
            (tool("Skill", {"skill": "invoker-chat-submit"}), [("invoker-chat-submit", "skill_tool")]),
            (tool("Bash", {"command": "cat engine/skills/make-pr/SKILL.md 2>/dev/null | head -150"}), [("make-pr", "shell_read")]),
            (tool("Read", {"path": f"{HOME}/.claude/skills/reflect/SKILL.md"}), [("reflect", "read")]),
            (tool("ReadFile", {"path": f"{HOME}/.cursor/skills-cursor/canvas/SKILL.md"}), [("canvas", "read")]),
            (tool("Read", {"file_path": f"{HOME}/.claude/skills/diu/SKILL.md"}), [("diu", "read")]),
            (tool("exec", CODEX_EXEC), [("invoker-make-pr", "shell_read")]),
        ]
        for payload, expected in cases:
            with self.subTest(tool=payload["tool_name"]):
                self.assertEqual(detect.tool_uses(payload), expected)

    def test_mentions_that_are_not_uses_are_ignored(self):
        cases = [
            tool("Glob", {"glob_pattern": "**/cat-mode/SKILL.md", "target_directory": HOME}),
            tool("Grep", {"path": f"{HOME}/.claude/skills", "pattern": "x", "glob": "**/SKILL.md"}),
            tool("Write", {"file_path": "/tmp/a.py", "content": f"open('{HOME}/.claude/skills/diu/SKILL.md')"}),
            tool("StrReplace", {"path": f"{HOME}/.claude/skills/diu/SKILL.md", "new_string": "x"}),
            tool("Task", {"prompt": f"cat {HOME}/.claude/skills/reflect/SKILL.md and follow it"}),
            tool("Agent", {"prompt": f"read {HOME}/.claude/skills/reflect/SKILL.md"}),
            tool("WebFetch", {"url": "https://raw.githubusercontent.com/o/r/main/.cursor/skills/verify-atlas/SKILL.md"}),
            tool("Bash", {"command": "rg -n 'skill' skills/ -g '*.md' | head"}),
            tool("Bash", {"command": "wc -l engine/skills/draft-pr/SKILL.md"}),
            tool("Read", {"file_path": f"{HOME}/notes/skills.md"}),
        ]
        for payload in cases:
            with self.subTest(tool=payload["tool_name"], data=json.dumps(payload["tool_input"])[:60]):
                self.assertEqual(detect.tool_uses(payload), [])


class TestPromptUses(unittest.TestCase):
    INSTALLED = {"cat-mode", "diu", "reflect"}

    def test_a_typed_command_at_the_start_counts(self):
        self.assertEqual(detect.prompt_uses({"prompt": "/cat-mode and add metrics"}, "claude", self.INSTALLED), [("cat-mode", "slash")])
        self.assertEqual(detect.prompt_uses({"prompt": "/diu"}, "cursor", self.INSTALLED), [("diu", "slash")])

    def test_codex_dollar_mentions_count_only_on_codex(self):
        self.assertEqual(detect.prompt_uses({"prompt": "fix it $reflect"}, "codex", self.INSTALLED), [("reflect", "mention")])
        self.assertEqual(detect.prompt_uses({"prompt": "fix it $reflect"}, "claude", self.INSTALLED), [])

    def test_paths_unknown_names_and_mid_sentence_mentions_do_not_count(self):
        for prompt in ("/tmp/x.log is empty", "/nosuchskill go", "the /cat-mode skill says so", "costs $5"):
            with self.subTest(prompt=prompt):
                self.assertEqual(detect.prompt_uses({"prompt": prompt}, "codex", self.INSTALLED), [])

    def test_installed_skills_reads_every_root_for_the_harness(self):
        with tempfile.TemporaryDirectory() as home:
            for root, name in ((".cursor/skills", "a"), (".cursor/skills-cursor", "b"), (".cursor/skills", "no-skill-md")):
                os.makedirs(os.path.join(home, root, name))
            for root, name in ((".cursor/skills", "a"), (".cursor/skills-cursor", "b")):
                open(os.path.join(home, root, name, "SKILL.md"), "w").close()
            self.assertEqual(detect.installed_skills("cursor", home), {"a", "b"})
            self.assertEqual(detect.installed_skills("claude", home), set())

    def test_an_unreadable_skill_folder_is_unchecked_not_empty(self):
        with patch.object(detect.os, "listdir", side_effect=PermissionError("denied")):
            self.assertIsNone(detect.installed_skills("claude", "/anywhere"))


class TestLog(unittest.TestCase):
    def setUp(self):
        self.metrics = tempfile.TemporaryDirectory()
        self.addCleanup(self.metrics.cleanup)
        env = patch.dict(os.environ, {"CATSTACK_HOOK_METRICS_DIR": self.metrics.name})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop(log.OPT_OUT_ENV, None)

    def rows(self):
        rows = []
        for name in sorted(os.listdir(self.metrics.name)):
            if name.startswith("events-"):
                with open(os.path.join(self.metrics.name, name), encoding="utf-8") as handle:
                    rows.extend(json.loads(line) for line in handle)
        return rows

    def run_main(self, harness, kind, stdin, allow=""):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(sys, "stdin", io.StringIO(stdin)), redirect_stdout(out), redirect_stderr(err):
            log.main(harness, kind, allow)
        return out.getvalue(), err.getvalue()

    def test_a_use_writes_one_row_with_skill_source_and_harness(self):
        out, err = self.run_main("claude", "tool", json.dumps(tool("Skill", {"skill": "diu"})))
        self.assertEqual((out, err), ("", ""))
        [row] = self.rows()
        self.assertEqual(
            {k: row[k] for k in ("hook", "harness", "session_id", "action", "reason", "skill")},
            {"hook": "skill-usage-log", "harness": "claude", "session_id": "s-1", "action": "skill_used", "reason": "skill_tool", "skill": "diu"},
        )

    def test_a_tool_call_that_uses_no_skill_writes_nothing(self):
        self.run_main("claude", "tool", json.dumps(tool("Bash", {"command": "ls"})))
        self.assertEqual(self.rows(), [])

    def test_opt_out_writes_nothing_and_still_allows_cursor(self):
        with patch.dict(os.environ, {log.OPT_OUT_ENV: "0"}):
            out, _ = self.run_main("cursor", "tool", json.dumps(tool("Skill", {"skill": "diu"})), '{"continue": true}\n')
        self.assertEqual(out, '{"continue": true}\n')
        self.assertEqual(self.rows(), [])

    def test_unreadable_payload_is_recorded_as_unchecked_and_reported(self):
        for stdin in ("{not json", "[1, 2]"):
            with self.subTest(stdin=stdin):
                out, err = self.run_main("cursor", "tool", stdin, '{"continue": true}\n')
                self.assertEqual(out, '{"continue": true}\n')
                self.assertTrue(err.startswith("catstack-hook-error skill-usage-log: "))
        self.assertEqual([(r["action"], r["reason"]) for r in self.rows()], [("skill_usage_unchecked", "bad_payload")] * 2)

    def test_unreadable_skill_folders_leave_typed_commands_unchecked(self):
        with patch.object(log, "installed_skills", return_value=None):
            _, err = self.run_main("claude", "prompt", json.dumps({"prompt": "/diu", "session_id": "s-2"}))
        self.assertIn("typed skill commands unchecked", err)
        self.assertEqual([(r["action"], r["reason"]) for r in self.rows()], [("skill_usage_unchecked", "skills_unreadable")])

    def test_every_entry_script_runs_as_a_real_process(self):
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        os.makedirs(os.path.join(home.name, ".codex", "skills", "reflect"))
        open(os.path.join(home.name, ".codex", "skills", "reflect", "SKILL.md"), "w").close()
        cases = [
            ("claude_pretooluse_log.py", tool("Skill", {"skill": "diu"}), ""),
            ("codex_pretooluse.py", tool("exec", CODEX_EXEC), ""),
            ("codex_prompt_submit.py", {"prompt": "go $reflect", "session_id": "s-3"}, ""),
            ("cursor_pretooluse.py", tool("Read", {"path": f"{HOME}/.claude/skills/reflect/SKILL.md"}), ""),
            ("cursor_before_submit.py", {"prompt": "hi"}, ""),
            ("claude_prompt_submit.py", {"prompt": "hi"}, ""),
        ]
        env = {**os.environ, "HOME": home.name, "CATSTACK_HOOK_METRICS_DIR": self.metrics.name}
        for script, payload, expected in cases:
            with self.subTest(script=script):
                proc = subprocess.run([sys.executable, os.path.join(HOOKS_DIR, script)], input=json.dumps(payload),
                                      capture_output=True, text=True, env=env, timeout=10)
                self.assertEqual((proc.returncode, proc.stdout, proc.stderr), (0, expected, ""))
        finding_rows = [row for row in self.rows() if row["rule_id"]]
        self.assertEqual(
            [(r["harness"], r["rule_id"], r["mode"], r["mode_source"]) for r in finding_rows],
            [("claude", "skill-usage-log.skill-tool", "off", "registry"),
             ("codex", "skill-usage-log.shell-read", "off", "registry"),
             ("codex", "skill-usage-log.mention", "off", "registry"),
             ("cursor", "skill-usage-log.read", "off", "registry")],
        )


if __name__ == "__main__":
    unittest.main()
