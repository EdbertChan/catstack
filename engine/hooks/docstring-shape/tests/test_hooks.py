#!/usr/bin/env python3
"""Tests for the docstring-shape PreToolUse hook."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOKS_DIR)

import claude_pretooluse  # noqa: E402
import detect  # noqa: E402
import proposed_edit  # noqa: E402


def run_hook(payload: dict):
    err = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with redirect_stderr(err):
            try:
                claude_pretooluse.main()
            except SystemExit as exc:
                return exc.code, err.getvalue()
    return 0, err.getvalue()


def write(path: str, content: str) -> dict:
    return {"tool_name": "Write", "tool_input": {"file_path": path, "content": content}}


def edit(path: str, old: str, new: str, replace_all: bool = False) -> dict:
    tool_input = {"file_path": path, "old_string": old, "new_string": new}
    if replace_all:
        tool_input["replace_all"] = True
    return {"tool_name": "Edit", "tool_input": tool_input}


def multi_edit(path: str, edits: list[tuple[str, str]]) -> dict:
    return {
        "tool_name": "MultiEdit",
        "tool_input": {"file_path": path, "edits": [{"old_string": old, "new_string": new} for old, new in edits]},
    }


FOUR_LINE_FUNCTION_DOCSTRING = (
    "def fetch_bytes(url, on_attempt, urlopen=None, sleep=None):\n"
    '    """The body of one GET as bytes. on_attempt() is called before every HTTP attempt,\n'
    "    retries included; urlopen and sleep default to urllib.request.urlopen and\n"
    "    time.sleep, looked up per call so tests can pass or patch them.\n"
    '    """\n'
    "    return b''\n"
)
MULTI_LINE_CLASS_DOCSTRING = (
    "class PipelineTreeWalker:\n"
    '    """Walks one pipeline tree over GraphQL: a root pipeline, its jobs, and every child pipeline a trigger job started.\n'
    "    A child pipeline lives in the same or another project and has its own jobs and trigger jobs, so the tree can be several levels deep.\n"
    "    Each request reads one layer of it: the root, then job pages, then child pages, then unread children as new seeds, until the request cap.\n"
    '    Every problem becomes an errors entry, and the result counts what was kept and what was dropped."""\n'
    "\n"
    "    def walk(self):\n"
    '        """Every pipeline in the tree, root first."""\n'
    "        return []\n"
)
ONE_LINE_DOCSTRING = (
    "def epoch_seconds(text):\n"
    '    """The timestamp in text as seconds since the epoch."""\n'
    "    return 0\n"
)
LONG_ONE_LINE_DOCSTRING = (
    "def epoch_seconds(text):\n"
    '    """The timestamp in text as seconds since the epoch, read from the first ISO 8601 date in the text '
    'or the first run of digits when no date is present."""\n'
    "    return 0\n"
)
MULTI_LINE_MODULE_DOCSTRING = (
    '"""Load steps from the ingest directory.\n'
    "\n"
    "Each step is read in order and failures stop the loader.\n"
    '"""\n'
    "STEPS = []\n"
)
SYNTAX_ERROR_RESULT = (
    "def fetch_bytes(url):\n"
    '    """The body of one GET as bytes."""\n'
    "    return b''\n"
    "def (:\n"
)


class TemporaryPythonFile:
    """A real .py file on disk for the Edit and MultiEdit payload shapes."""

    def __init__(self, content: str, name: str = "module.py") -> None:
        self.content = content
        self.name = name
        self.directory = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.directory.name, name)

    def __enter__(self) -> str:
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(self.content)
        return self.path

    def __exit__(self, *_exit_arguments) -> None:
        self.directory.cleanup()


class TestFires(unittest.TestCase):
    def test_fires_on_a_four_line_function_docstring_written_to_a_new_file(self):
        code, err = run_hook(write("/repo/http_client.py", FOUR_LINE_FUNCTION_DOCSTRING))
        self.assertEqual(code, 2)
        self.assertIn("function fetch_bytes (line 2) spans 4 lines", err)

    def test_fires_on_a_four_line_function_docstring_added_by_edit(self):
        with TemporaryPythonFile("import urllib.request\n") as path:
            payload = edit(path, "import urllib.request\n", "import urllib.request\n\n\n" + FOUR_LINE_FUNCTION_DOCSTRING)
            message = detect.decide(payload)
        self.assertIsNotNone(message)
        self.assertIn("fetch_bytes", message)

    def test_fires_on_a_one_line_docstring_over_120_characters(self):
        message = detect.decide(write("/repo/times.py", LONG_ONE_LINE_DOCSTRING))
        self.assertIsNotNone(message)
        self.assertIn("characters; the cap is 120", message)

    def test_fires_on_a_multi_line_module_docstring(self):
        message = detect.decide(write("/repo/ingest/steps_loader.py", MULTI_LINE_MODULE_DOCSTRING))
        self.assertIsNotNone(message)
        self.assertIn("module steps_loader.py (line 1) spans 4 lines", message)

    def test_fires_through_multiedit_applied_in_order(self):
        with TemporaryPythonFile("def fetch_bytes(url):\n    return b''\n") as path:
            payload = multi_edit(
                path,
                [
                    ("def fetch_bytes(url):\n", "def fetch_bytes(url, on_attempt):\n"),
                    ("def fetch_bytes(url, on_attempt):\n", FOUR_LINE_FUNCTION_DOCSTRING.split("    return b''\n")[0]),
                ],
            )
            message = detect.decide(payload)
        self.assertIsNotNone(message)
        self.assertIn("spans 4 lines", message)

    def test_fires_when_replace_all_rewrites_every_docstring(self):
        original = ONE_LINE_DOCSTRING + "\n" + ONE_LINE_DOCSTRING.replace("epoch_seconds", "epoch_minutes")
        with TemporaryPythonFile(original) as path:
            payload = edit(
                path,
                '    """The timestamp in text as seconds since the epoch."""\n',
                '    """The timestamp in text.\n\n    Read from the first date.\n    """\n',
                replace_all=True,
            )
            findings = detect.detect(payload)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule_id, detect.RULE_DOCSTRING_SHAPE)
        self.assertEqual(findings[0].evidence.count("spans 4 lines"), 2)


class TestStaysSilent(unittest.TestCase):
    def test_stays_silent_on_a_multi_line_class_docstring(self):
        self.assertIsNone(detect.decide(write("/repo/pipeline_tree.py", MULTI_LINE_CLASS_DOCSTRING)))

    def test_stays_silent_on_a_one_line_docstring_under_120_characters(self):
        self.assertIsNone(detect.decide(write("/repo/times.py", ONE_LINE_DOCSTRING)))

    def test_stays_silent_on_a_docstring_the_edit_does_not_touch(self):
        with TemporaryPythonFile(FOUR_LINE_FUNCTION_DOCSTRING) as path:
            payload = edit(path, "    return b''\n", "    return b'' + b''\n")
            self.assertIsNone(detect.decide(payload))

    def test_stays_silent_on_non_python_files(self):
        self.assertIsNone(detect.decide(write("/repo/notes.md", MULTI_LINE_MODULE_DOCSTRING)))
        self.assertIsNone(detect.decide(write("/repo/app.ts", FOUR_LINE_FUNCTION_DOCSTRING)))

    def test_stays_silent_on_a_multi_line_string_that_is_not_a_docstring(self):
        text = "QUERY = '''\nquery {\n  pipeline { id }\n}\n'''\n"
        self.assertIsNone(detect.decide(write("/repo/queries.py", text)))

    def test_stays_silent_on_tools_that_do_not_edit(self):
        self.assertIsNone(detect.decide({"tool_name": "Bash", "tool_input": {"command": "cat a.py"}}))
        self.assertIsNone(detect.decide({"tool_name": "Edit", "tool_input": "not a dict"}))


class TestUnchecked(unittest.TestCase):
    def assert_unchecked(self, payload: dict, expected_reason_fragment: str) -> None:
        findings = detect.detect(payload)
        self.assertEqual(findings, [])
        unchecked = payload.get("_catstack_unchecked_findings")
        self.assertEqual(len(unchecked), 1)
        self.assertEqual(unchecked[0].rule_id, detect.RULE_UNCHECKED)
        self.assertIn(expected_reason_fragment, unchecked[0].message)
        self.assertIn(expected_reason_fragment, payload["_catstack_stderr_lines"][0])

    def test_unchecked_on_a_syntax_error_in_the_resulting_text(self):
        self.assert_unchecked(write("/repo/http_client.py", SYNTAX_ERROR_RESULT), "does not parse")

    def test_unchecked_syntax_error_allows_the_edit_and_says_so_on_stderr(self):
        code, err = run_hook(write("/repo/http_client.py", SYNTAX_ERROR_RESULT))
        self.assertEqual(code, 0)
        self.assertIn("docstring-shape: the edited /repo/http_client.py does not parse", err)

    def test_unchecked_when_the_edited_file_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = edit(os.path.join(directory, "missing.py"), "a = 1\n", "a = 2\n")
            self.assert_unchecked(payload, "does not exist")

    def test_unchecked_when_old_string_is_not_in_the_file(self):
        with TemporaryPythonFile("a = 1\n") as path:
            self.assert_unchecked(edit(path, "b = 2\n", "b = 3\n"), "old_string was not found")

    def test_unchecked_when_the_file_is_too_large(self):
        with TemporaryPythonFile("a = 1\n") as path:
            with patch.object(proposed_edit, "MAX_FILE_BYTES", 2):
                self.assert_unchecked(edit(path, "a = 1\n", "a = 2\n"), "is over 2 bytes")

    def test_unchecked_when_the_file_is_not_utf8(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "latin.py")
            with open(path, "wb") as handle:
                handle.write(b"name = '\xe9'\n")
            self.assert_unchecked(edit(path, "name", "label"), "could not be read")

    def test_unchecked_syntax_error_writes_an_unchecked_event_row(self):
        with tempfile.TemporaryDirectory() as metrics_dir:
            with patch.dict(os.environ, {"CATSTACK_HOOK_METRICS_DIR": metrics_dir, "CATSTACK_HOOK_TEST_MODEL": "claude-sonnet-5"}):
                code, _err = run_hook(write("/repo/http_client.py", SYNTAX_ERROR_RESULT))
            rows = []
            for name in os.listdir(metrics_dir):
                if not name.endswith(".jsonl"):
                    continue
                with open(os.path.join(metrics_dir, name), encoding="utf-8") as handle:
                    rows.extend(json.loads(line) for line in handle.read().splitlines())
        self.assertEqual(code, 0)
        unchecked_rows = [row for row in rows if row["action"] == "unchecked"]
        self.assertEqual(len(unchecked_rows), 1, rows)
        self.assertEqual(unchecked_rows[0]["rule_id"], detect.RULE_UNCHECKED)
        self.assertEqual(unchecked_rows[0]["hook"], "docstring-shape")

    def test_fails_open_on_garbage_stdin(self):
        err = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("nope")):
            with redirect_stderr(err):
                claude_pretooluse.main()
        self.assertEqual(err.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
