#!/usr/bin/env python3
"""Every catstack behavior flag is read through flags.py, and every one is
listed where a user will look for it.

A hook that reads its flag with `os.environ.get` only sees the shell. The
same flag written to `.env` or `~/.catstack.env` then does nothing, and
nothing says so. A hook that carries its own copy of the file reader drifts
from this one: cat-mode-default's copy read an unreadable file as "not set".

Run: python3 -m unittest discover -s engine/hooks/_flags/tests -v
"""
from __future__ import annotations

import ast
import os
import re
import sys
import unittest

FLAGS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS_DIR = os.path.dirname(FLAGS_DIR)
REPO_ROOT = os.path.dirname(os.path.dirname(HOOKS_DIR))
sys.path.insert(0, FLAGS_DIR)

import flags  # noqa: E402

READER_DEF_RE = re.compile(r"^def (env_file_candidates|read_flag_from_file|resolve_flag)\(", re.M)
IMPORTS_FLAGS_RE = re.compile(r"^\s*(import flags\b|from flags import )", re.M)


def code_strings(text):
    """String literals in the code, minus docstrings: a docstring that
    mentions a flag explains it and does not read it."""
    tree = ast.parse(text)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    return [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings
    ]


def hook_sources():
    for root, dirs, files in os.walk(HOOKS_DIR):
        dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__", "_flags")]
        for name in files:
            if name.endswith(".py"):
                path = os.path.join(root, name)
                with open(path, encoding="utf-8") as handle:
                    yield os.path.relpath(path, REPO_ROOT), handle.read()


class OneReaderTest(unittest.TestCase):
    def test_no_hook_carries_its_own_flag_file_reader(self):
        copies = [path for path, text in hook_sources() if READER_DEF_RE.search(text)]
        self.assertEqual([], copies, "use flags.resolve_flag instead of a copied reader")

    def test_every_file_that_names_a_behavior_flag_imports_flags(self):
        missing = []
        for path, text in hook_sources():
            named = [f for f in flags.BEHAVIOR_FLAGS if any(s.startswith(f) for s in code_strings(text))]
            if named and not IMPORTS_FLAGS_RE.search(text):
                missing.append(f"{path} names {named[0]}")
        self.assertEqual([], missing)

    def test_a_docstring_mention_is_not_a_read(self):
        text = '"""Off unless CATSTACK_REFLECT_ENFORCEMENT is on."""\nKEY = "CATSTACK_HOOK_FRESHNESS"\n'
        self.assertEqual(["CATSTACK_HOOK_FRESHNESS"], code_strings(text))

    def test_every_behavior_flag_is_documented_for_the_user(self):
        with open(os.path.join(FLAGS_DIR, "README.md"), encoding="utf-8") as handle:
            readme = handle.read()
        with open(os.path.join(REPO_ROOT, ".env.example"), encoding="utf-8") as handle:
            example = handle.read()
        for flag in flags.BEHAVIOR_FLAGS:
            with self.subTest(flag=flag):
                self.assertIn(f"| `{flag}", readme)
                self.assertIn(flag, example)


if __name__ == "__main__":
    unittest.main()
