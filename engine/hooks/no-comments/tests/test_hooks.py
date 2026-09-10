#!/usr/bin/env python3
"""Tests for the no-comments PreToolUse hook.

Run: python3 -m unittest discover -s engine/hooks/no-comments/tests -v
"""
from __future__ import annotations

import io
import json
import os
import sys
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


def edit(path: str, new: str) -> dict:
    return {"tool_name": "Edit", "tool_input": {"file_path": path, "old_string": "x", "new_string": new}}


REAL_PY_COMMENT = (
    "    if payload.get(\"stop_hook_active\"):\n"
    "        # This block already fired once this turn and the agent has rewritten.\n"
    "        return\n"
)
REAL_JS_COMMENT = "const x = 1; // fallback when config is missing\n"

MARKDOWN_FIXTURE_IN_TRIPLE_QUOTES = (
    'MANUAL_NO_FLAG = """---\n'
    "name: admin-bypass-sweep\n"
    "---\n"
    "\n"
    "# admin-bypass-sweep\n"
    '"""\n'
)
DOCSTRING_WITH_TRAILING_HASH_USAGE = (
    '"""Which skills may the model fire on its own?\n'
    "\n"
    "    python3 scripts/check_skill_trigger_policy.py           # verify\n"
    "    python3 scripts/check_skill_trigger_policy.py --write   # regenerate doc\n"
    '"""\n'
)
COMMENT_AFTER_A_CLOSED_TRIPLE_QUOTED_STRING = (
    MARKDOWN_FIXTURE_IN_TRIPLE_QUOTES + "# real shape: the flag was missing here\n"
)
CSS_UNIVERSAL_SELECTOR = (
    "* {\n"
    "  box-sizing: border-box;\n"
    "}\n"
    "*, *::before, *::after { margin: 0; }\n"
)
CSS_BLOCK_COMMENT = (
    "/*\n"
    " * reset spacing before the grid lays out\n"
    " */\n"
    "* { margin: 0; }\n"
)
DOCBLOCK_TAIL_WITHOUT_OPENER = (
    "   * @param x the raw input\n"
    "   */\n"
    "function f(x) {}\n"
)
HTML_SCRIPT_BLOCK_COMMENT = (
    "<script>\n"
    "/*\n"
    " * wire the menu before paint\n"
    " */\n"
    "</script>\n"
)
HTML_VERBATIM_QUOTE_WITH_LEADING_ASTERISK = (
    "<blockquote>\n"
    "* the hook forced worse CSS\n"
    "</blockquote>\n"
)
CSS_OPENER_INSIDE_A_STRING = (
    'a::before { content: "/*"; }\n'
    "* { margin: 0; }\n"
)


class TestBlocks(unittest.TestCase):
    def test_blocks_python_line_comment_from_real_session(self):
        code, err = run_hook(edit("/repo/hook.py", REAL_PY_COMMENT))
        self.assertEqual(code, 2)
        self.assertIn("This block already fired", err)

    def test_blocks_trailing_js_comment(self):
        self.assertIsNotNone(detect.decide(edit("/repo/a.ts", REAL_JS_COMMENT)))

    def test_blocks_block_comment_and_html_comment(self):
        self.assertIsNotNone(detect.decide(edit("/repo/a.js", "/* why */\nlet a = 1;\n")))
        self.assertIsNotNone(detect.decide(edit("/repo/a.html", "<!-- nav -->\n<div></div>\n")))

    def test_blocks_a_real_comment_after_a_closed_triple_quoted_string(self):
        hits = detect.comment_lines("/r/t.py", COMMENT_AFTER_A_CLOSED_TRIPLE_QUOTED_STRING)
        self.assertEqual(hits, ["# real shape: the flag was missing here"])

    def test_blocks_a_css_block_comment_and_spares_the_selector_after_it(self):
        hits = detect.comment_lines("/r/a.css", CSS_BLOCK_COMMENT)
        self.assertEqual(hits, ["/*", "* reset spacing before the grid lays out"])

    def test_blocks_a_docblock_tail_whose_opener_is_outside_the_edit(self):
        hits = detect.comment_lines("/r/a.ts", DOCBLOCK_TAIL_WITHOUT_OPENER)
        self.assertEqual(hits, ["* @param x the raw input"])

    def test_blocks_a_block_comment_in_an_html_script(self):
        hits = detect.comment_lines("/r/a.html", HTML_SCRIPT_BLOCK_COMMENT)
        self.assertEqual(hits, ["/*", "* wire the menu before paint"])

    def test_blocks_write_and_multiedit_shapes(self):
        w = {"tool_name": "Write", "tool_input": {"file_path": "/r/x.sh", "content": "#!/bin/bash\n# step one\nls\n"}}
        m = {"tool_name": "MultiEdit", "tool_input": {"file_path": "/r/x.py", "edits": [{"new_string": "a = 1\n"}, {"new_string": "# TODO\n"}]}}
        self.assertIsNotNone(detect.decide(w))
        self.assertIsNotNone(detect.decide(m))


class TestAllows(unittest.TestCase):
    def test_allows_directives_and_shebang(self):
        text = "#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\nimport x  # noqa: E402\ny = 1  # type: ignore\n# pragma: no cover\n"
        self.assertEqual(detect.comment_lines("/r/a.py", text), [])
        js = "// eslint-disable-next-line no-console\n// @ts-ignore\n/* istanbul ignore next */\n// SPDX-License-Identifier: MIT\n"
        self.assertEqual(detect.comment_lines("/r/a.ts", js), [])

    def test_allows_hash_and_slashes_inside_strings_and_urls(self):
        self.assertEqual(detect.comment_lines("/r/a.py", "url = 'https://x.y/#frag'\ncolor = \"#fff\"\n"), [])
        self.assertEqual(detect.comment_lines("/r/a.ts", "const u = 'https://a.b/c';\n"), [])

    def test_allows_docstrings_and_plain_code(self):
        self.assertEqual(detect.comment_lines("/r/a.py", '"""Module doc.\n\nMore prose.\n"""\ndef f():\n    return 1\n'), [])

    def test_allows_markdown_headings_inside_a_python_triple_quoted_fixture(self):
        self.assertEqual(detect.comment_lines("/r/t.py", MARKDOWN_FIXTURE_IN_TRIPLE_QUOTES), [])

    def test_allows_trailing_hash_usage_lines_inside_a_module_docstring(self):
        self.assertEqual(detect.comment_lines("/r/a.py", DOCSTRING_WITH_TRAILING_HASH_USAGE), [])

    def test_allows_the_css_universal_selector(self):
        self.assertEqual(detect.comment_lines("/r/a.css", CSS_UNIVERSAL_SELECTOR), [])
        self.assertIsNone(detect.decide(edit("/r/a.scss", CSS_UNIVERSAL_SELECTOR)))

    def test_allows_a_leading_asterisk_in_a_verbatim_html_quote(self):
        self.assertEqual(detect.comment_lines("/r/a.html", HTML_VERBATIM_QUOTE_WITH_LEADING_ASTERISK), [])

    def test_allows_a_selector_after_a_block_opener_inside_a_string(self):
        self.assertEqual(detect.comment_lines("/r/a.css", CSS_OPENER_INSIDE_A_STRING), [])

    def test_allows_non_code_files(self):
        self.assertIsNone(detect.decide(edit("/r/README.md", "# Heading\n")))
        self.assertIsNone(detect.decide(edit("/r/ci.yml", "# comment in yaml\n")))
        self.assertIsNone(detect.decide(edit("/r/x.json", "{}\n")))

    def test_allows_shell_variable_and_zsh_parameter_forms(self):
        self.assertEqual(detect.comment_lines("/r/a.sh", 'echo "${#arr[@]}"\nx=${y#prefix}\n'), [])

    def test_fails_open_on_garbage_stdin(self):
        err = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO("nope")):
            with redirect_stderr(err):
                claude_pretooluse.main()
        self.assertEqual(err.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
