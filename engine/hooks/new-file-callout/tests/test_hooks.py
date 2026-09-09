#!/usr/bin/env python3
"""Tests for the new-file-callout Stop hook.

Run: python3 -m unittest discover -s engine/hooks/new-file-callout/tests -v

Each fixture builds a throwaway git repo with the named untracked files and
a one-turn transcript (a human message, optionally a Write or a subagent
task-notification). The fires fixture is the real case: a subagent created
`install_cursor_session_hygiene.py` at the repo root and the parent reply
listed PR links without naming it.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATSTACK_ROOT = str(Path(__file__).resolve().parents[4])
sys.path.insert(0, os.path.join(CATSTACK_ROOT, "scripts"))
FIXTURES = os.path.join(HOOK_DIR, "tests", "fixtures")
sys.path.insert(0, HOOK_DIR)

import claude_stop_check  # noqa: E402
import detect  # noqa: E402
from git_test_repo import init_repo  # noqa: E402


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)


def make_repo(new_files, stale=False):
    tmp = tempfile.TemporaryDirectory()
    init_repo(tmp.name)
    for rel in new_files:
        path = os.path.join(tmp.name, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write("x\n")
        if stale:
            old = time.time() - 3600
            os.utime(path, (old, old))
    return tmp


def make_lines(case):
    started = time.time() - 60
    iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(started)) + ".000Z"
    lines = [{"type": "user", "timestamp": iso, "message": {"role": "user", "content": "land it"}}]
    if case.get("write_path"):
        lines.append({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "w1", "name": "Write",
             "input": {"file_path": case["write_path"], "content": "x"}}]}})
    if case.get("notification"):
        lines.append({"type": "user", "message": {"role": "user", "content":
            f"<task-notification>\n<status>completed</status>\n<summary>{case['notification']}</summary>\n</task-notification>"}})
    return lines


def transcript_file(lines):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    tmp.write("\n".join(json.dumps(line) for line in lines) + "\n")
    tmp.close()
    return tmp.name


def run_hook(payload):
    err = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with redirect_stderr(err):
            try:
                claude_stop_check.main()
            except SystemExit as exc:
                return exc.code, err.getvalue()
    return 0, err.getvalue()


class TestBlocksUnnamedNewFiles(unittest.TestCase):
    def test_blocks_each_fires_fixture(self):
        for case in load("new_files_fires.json"):
            with self.subTest(label=case["label"]):
                repo = make_repo(case["new_files"], stale=case.get("stale", False))
                try:
                    verdict = detect.decide_from_lines(case["reply"], make_lines(case), repo.name)
                finally:
                    repo.cleanup()
                self.assertIsNotNone(verdict)
                for rel in case["new_files"]:
                    self.assertIn(rel, verdict)

    def test_hook_blocks_subagent_root_file_with_exit_2(self):
        case = load("new_files_fires.json")[0]
        repo = make_repo(case["new_files"])
        path = transcript_file(make_lines(case))
        try:
            code, err = run_hook({
                "last_assistant_message": case["reply"], "transcript_path": path, "cwd": repo.name,
            })
        finally:
            os.unlink(path)
            repo.cleanup()
        self.assertEqual(code, 2)
        self.assertIn("install_cursor_session_hygiene.py", err)
        self.assertIn("new-file-callout", err)

    def test_blocks_shell_redirect_created_root_file(self):
        repo = make_repo(["pr-body.md"], stale=True)
        lines = [{"type": "user", "message": {"role": "user", "content": "open the pr"}},
                 {"type": "assistant", "message": {"role": "assistant", "content": [
                     {"type": "tool_use", "id": "b1", "name": "Bash",
                      "input": {"command": "cat > pr-body.md <<'EOF'\n## Summary\nEOF"}}]}}]
        try:
            verdict = detect.decide_from_lines("PR is open: #8.", lines, repo.name)
        finally:
            repo.cleanup()
        self.assertIsNotNone(verdict)
        self.assertIn("pr-body.md", verdict)


class TestAllowsNamedOrUntouchedFiles(unittest.TestCase):
    def test_allows_each_silent_fixture(self):
        for case in load("new_files_silent.json"):
            with self.subTest(label=case["label"]):
                repo = make_repo(case["new_files"], stale=case.get("stale", False))
                try:
                    verdict = detect.decide_from_lines(case["reply"], make_lines(case), repo.name)
                finally:
                    repo.cleanup()
                self.assertIsNone(verdict)

    def test_allows_clean_repo(self):
        repo = make_repo([])
        try:
            self.assertIsNone(detect.decide_from_lines("done", make_lines({}), repo.name))
        finally:
            repo.cleanup()

    def test_fails_open_outside_a_git_repo(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            self.assertIsNone(detect.decide_from_lines("done", [], tmp.name))
        finally:
            tmp.cleanup()

    def test_allows_when_stop_hook_active(self):
        self.assertIsNone(detect.decide({"last_assistant_message": "x", "stop_hook_active": True}))

    def test_fails_open_on_garbage_stdin(self):
        err = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("not json")):
            with redirect_stderr(err):
                claude_stop_check.main()
        self.assertEqual(err.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
