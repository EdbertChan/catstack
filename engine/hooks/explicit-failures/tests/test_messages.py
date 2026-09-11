#!/usr/bin/env python3
"""Tests for the error-message shapes (messages.py) and their wiring into the hook report.

Run: python3 -m unittest discover -s engine/hooks/explicit-failures/tests -v
"""
from __future__ import annotations

import os
import sys
import unittest

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(HOOK_DIR, "tests", "fixtures")
sys.path.insert(0, HOOK_DIR)

import detect  # noqa: E402
from messages import MESSAGE_PRINCIPLE, scan_python_messages  # noqa: E402


def fixture(name: str) -> str:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return handle.read()


def report(name: str, content: str | None = None) -> list[str]:
    text = fixture(name) if content is None else content
    return detect.report_lines("Write", {"file_path": f"/repo/{name}", "content": text})


class TestMessagesFire(unittest.TestCase):
    def test_fires_on_vague_message_fixture_through_the_hook_report(self):
        self.assertEqual(
            report("vague_message_fires.py"),
            [
                f'/repo/vague_message_fires.py:3: `raise ValueError("invalid input")` names no cause, value, or expectation — {MESSAGE_PRINCIPLE}',
                f"/repo/vague_message_fires.py:7: `raise RuntimeError(...)` inside `except ... as err` drops `err`; chain it with `from err` — {MESSAGE_PRINCIPLE}",
                f"/repo/vague_message_fires.py:12: `raise ValueError()` names no cause, value, or expectation — {MESSAGE_PRINCIPLE}",
                f'/repo/vague_message_fires.py:13: `raise Exception("Something went wrong.")` names no cause, value, or expectation — {MESSAGE_PRINCIPLE}',
            ],
        )

    def test_fires_on_an_edit_fragment_that_is_indented(self):
        fragment = "    if not rows:\n        raise ValueError('bad data')\n"
        hits = scan_python_messages(fragment)
        self.assertEqual([line for line, _ in hits], [2])

    def test_fires_on_a_bash_heredoc_with_no_target_path(self):
        command = "python3 - <<'EOF'\nraise RuntimeError('failed')\nEOF"
        hits = detect.report_lines("Bash", {"command": command})
        self.assertEqual(len(hits), 1, hits)
        self.assertIn("<heredoc>:1: `raise RuntimeError(\"failed\")`", hits[0])


class TestMessagesStaySilent(unittest.TestCase):
    def test_silent_on_vague_message_silent_fixture(self):
        self.assertEqual(report("vague_message_silent.py"), [])

    def test_silent_on_reraising_a_saved_exception_instance(self):
        text = "def retry(last_exc):\n    raise last_exc\n"
        self.assertEqual(scan_python_messages(text), [])

    def test_silent_on_a_handler_without_a_name(self):
        text = "try:\n    run()\nexcept OSError:\n    raise RuntimeError(f'could not run {cmd}')\n"
        self.assertEqual(scan_python_messages(text), [])

    def test_silent_on_a_nested_function_inside_a_handler(self):
        text = (
            "try:\n    run()\nexcept OSError as err:\n"
            "    def later(path):\n        raise KeyError(f'missing {path}')\n"
            "    raise RuntimeError('run failed') from err\n"
        )
        self.assertEqual(scan_python_messages(text), [])

    def test_silent_on_javascript_files(self):
        self.assertEqual(report("x.ts", 'throw new Error("failed")\n'), [])

    def test_unparseable_fragment_fails_open(self):
        self.assertEqual(scan_python_messages("raise ValueError('invalid input'\n"), [])

    def test_empty_text_fails_open(self):
        self.assertEqual(scan_python_messages(""), [])


if __name__ == "__main__":
    unittest.main()
