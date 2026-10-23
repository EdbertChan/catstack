#!/usr/bin/env python3
"""Tests for the short-name PreToolUse hook."""
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


def edit(path: str, old: str, new: str) -> dict:
    return {"tool_name": "Edit", "tool_input": {"file_path": path, "old_string": old, "new_string": new}}


class TemporaryPythonFile:
    """A real .py file on disk for the Edit payload shape."""

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


def new_path(directory: str, *parts: str) -> str:
    return os.path.join(directory, *parts)


class TestFires(unittest.TestCase):
    def test_fires_on_a_two_letter_def_with_a_one_letter_parameter(self):
        with tempfile.TemporaryDirectory() as directory:
            code, err = run_hook(write(new_path(directory, "times.py"), "def ts(s):\n    return int(s)\n"))
        self.assertEqual(code, 2)
        self.assertIn("function ts (line 1) 'ts' is 2 letter(s)", err)
        self.assertIn("parameter s (line 1) 's' is 1 letter(s)", err)

    def test_fires_on_a_leading_underscore_three_letter_def(self):
        with tempfile.TemporaryDirectory() as directory:
            message = detect.decide(write(new_path(directory, "ids.py"), "def _gid(value):\n    return value\n"))
        self.assertIsNotNone(message)
        self.assertIn("function _gid (line 1) 'gid' is three letters and not an accepted word", message)

    def test_fires_on_a_new_file_whose_stem_starts_with_an_abbreviation(self):
        with tempfile.TemporaryDirectory() as directory:
            os.makedirs(new_path(directory, "ingest"))
            message = detect.decide(write(new_path(directory, "ingest", "dd_steps_loader.py"), "STEPS = []\n"))
        self.assertIsNotNone(message)
        self.assertIn("file dd_steps_loader.py (line 0) 'dd' is an abbreviation", message)

    def test_fires_on_a_new_non_python_file_with_a_two_letter_stem(self):
        with tempfile.TemporaryDirectory() as directory:
            message = detect.decide(write(new_path(directory, "ui.css"), "* { margin: 0; }\n"))
        self.assertIsNotNone(message)
        self.assertIn("file ui.css (line 0) 'ui' is 2 letter(s)", message)

    def test_fires_on_a_denied_attribute_assignment(self):
        original = "class Graph:\n    def __init__(self):\n        self.predecessors = []\n"
        with TemporaryPythonFile(original) as path:
            message = detect.decide(edit(path, "        self.predecessors = []\n", "        self.predecessors = []\n        self.preds = []\n"))
        self.assertIsNotNone(message)
        self.assertIn("attribute preds (line 4) 'preds' is an abbreviation", message)

    def test_fires_on_a_denied_parameter_and_class_field(self):
        text = "class Request:\n    cfg: dict\n\n    def send(self, params):\n        return params\n"
        with tempfile.TemporaryDirectory() as directory:
            findings = detect.detect(write(new_path(directory, "request.py"), text))
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule_id, detect.RULE_SHORT_NAME)
        self.assertIn("attribute cfg line 2", findings[0].evidence)
        self.assertIn("parameter params line 4", findings[0].evidence)


class TestStaysSilent(unittest.TestCase):
    def assert_silent(self, text: str, name: str = "module.py") -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(detect.decide(write(new_path(directory, name), text)))

    def test_stays_silent_on_spelled_out_def_and_parameter(self):
        self.assert_silent("def epoch_seconds(text):\n    return int(text)\n")

    def test_stays_silent_on_an_accepted_short_word_part(self):
        self.assert_silent("def numeric_id(value):\n    return int(value)\n")

    def test_stays_silent_on_a_parameter_named_sha(self):
        self.assert_silent("def commit_subject(sha):\n    return sha\n")

    def test_stays_silent_on_a_spelled_out_attribute(self):
        original = "class Graph:\n    def __init__(self):\n        self.nodes = []\n"
        with TemporaryPythonFile(original) as path:
            self.assertIsNone(detect.decide(edit(path, "        self.nodes = []\n", "        self.nodes = []\n        self.predecessors = []\n")))

    def test_stays_silent_on_english_two_letter_words_and_dunders(self):
        self.assert_silent("class Reader:\n    def __eq__(self, other):\n        return self.is_code_file(other)\n\n    def is_code_file(self, path_to_check):\n        return True\n")

    def test_stays_silent_on_sentence_shaped_test_names_and_real_three_letter_words(self):
        self.assert_silent(
            "class Checks:\n"
            "    def test_fires_on_a_new_file_with_a_bad_stem_over_120_characters(self):\n"
            "        return self.hit_finding(non_python=True)\n\n"
            "    def hit_finding(self, non_python):\n"
            "        return non_python\n"
        )

    def test_stays_silent_on_loop_and_comprehension_variables(self):
        self.assert_silent("def total(rows):\n    squares = [r * r for r in rows]\n    for i in rows:\n        squares.append(i)\n    return sum(squares)\n")

    def test_stays_silent_on_a_short_name_the_edit_does_not_touch(self):
        original = "def ts(s):\n    return int(s)\n\n\ndef epoch_seconds(text):\n    return ts(text)\n"
        with TemporaryPythonFile(original) as path:
            self.assertIsNone(detect.decide(edit(path, "    return ts(text)\n", "    return ts(text.strip())\n")))

    def test_stays_silent_on_a_lambda_parameter(self):
        self.assert_silent("ORDER = sorted([3, 1], key=lambda x: -x)\n")

    def test_stays_silent_when_write_overwrites_an_existing_short_stem(self):
        with TemporaryPythonFile("x = 1\n", name="ci.py") as path:
            self.assertIsNone(detect.decide(write(path, "epoch_seconds = 1\n")))

    def test_stays_silent_on_edits_to_non_python_files(self):
        with TemporaryPythonFile("# notes\n", name="notes.md") as path:
            self.assertIsNone(detect.decide(edit(path, "# notes\n", "# notes\n\ndef ts(s): pass\n")))

    def test_stays_silent_on_tools_that_do_not_edit(self):
        self.assertIsNone(detect.decide({"tool_name": "Bash", "tool_input": {"command": "python3 ts.py"}}))


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
        with tempfile.TemporaryDirectory() as directory:
            self.assert_unchecked(write(new_path(directory, "broken.py"), "def epoch_seconds(:\n"), "does not parse")

    def test_unchecked_syntax_error_allows_the_edit_and_says_so_on_stderr(self):
        with tempfile.TemporaryDirectory() as directory:
            code, err = run_hook(write(new_path(directory, "broken.py"), "def epoch_seconds(:\n"))
        self.assertEqual(code, 0)
        self.assertIn("short-name: the edited", err)
        self.assertIn("does not parse", err)

    def test_unchecked_when_the_edited_file_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assert_unchecked(edit(new_path(directory, "missing.py"), "a = 1\n", "a = 2\n"), "does not exist")

    def test_new_file_with_a_bad_stem_still_fires_when_its_body_does_not_parse(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = write(new_path(directory, "dd_loader.py"), "def (:\n")
            findings = detect.detect(payload)
        self.assertEqual(len(findings), 1)
        self.assertIn("file dd_loader.py", findings[0].evidence)
        self.assertEqual(payload["_catstack_unchecked_findings"][0].rule_id, detect.RULE_UNCHECKED)

    def test_fails_open_on_garbage_stdin(self):
        err = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("nope")):
            with redirect_stderr(err):
                claude_pretooluse.main()
        self.assertEqual(err.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
