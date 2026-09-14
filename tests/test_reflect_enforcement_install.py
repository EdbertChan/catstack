#!/usr/bin/env python3
"""install.sh installs the automate-me rule only when CATSTACK_REFLECT_ENFORCEMENT is on.

The four reflect hooks already read the flag at run time. The always-on rule
"same complaint type twice: invoke automate-me" used to ship to every harness
regardless. These tests run the real install.sh against a fake home, with the
flag on, off, and flipped from on to off, and read what each harness got.
"""
from __future__ import annotations

import os
import tempfile
import unittest

from test_install import REPO_ROOT, run_install

KEY = "CATSTACK_REFLECT_ENFORCEMENT"
CODEX_BEGIN = "<!-- catstack-reflect-enforcement -->"
UNGATED_RULE_FILES = (
    "engine/CLAUDE.core.md",
    "corpus/CLAUDE.learned.md",
)


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class ReflectEnforcementInstall(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = self.tmp.name

    def install(self, value):
        result = run_install(self.home, extra_env={KEY: value})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def local_rule(self):
        return read(os.path.join(self.home, "reflect-enforcement.local.md"))

    def cursor_rule(self):
        return os.path.join(self.home, ".cursor", "rules", "reflect-enforcement.mdc")

    def codex_agents(self):
        return read(os.path.join(self.home, ".codex", "AGENTS.md"))

    def test_on_installs_the_rule_for_all_three_harnesses(self):
        self.install("1")
        self.assertIn("automate-me", self.local_rule())
        self.assertTrue(os.path.islink(self.cursor_rule()))
        self.assertEqual(os.readlink(self.cursor_rule()), os.path.join(REPO_ROOT, "engine", "hooks", "_flags", "rules", "reflect-enforcement.mdc"))
        self.assertIn(CODEX_BEGIN, self.codex_agents())

    def test_off_installs_no_rule_anywhere(self):
        result = self.install("0")
        self.assertNotIn("automate-me", self.local_rule())
        self.assertIn("off", self.local_rule())
        self.assertFalse(os.path.lexists(self.cursor_rule()))
        self.assertNotIn(CODEX_BEGIN, self.codex_agents())
        self.assertIn("catstack-named-constraints", self.codex_agents())
        self.assertIn("no automate-me rule", result.stdout)

    def test_turning_it_off_removes_what_on_installed(self):
        self.install("1")
        result = self.install("0")
        self.assertFalse(os.path.lexists(self.cursor_rule()))
        self.assertNotIn(CODEX_BEGIN, self.codex_agents())
        self.assertIn("remove  reflect-enforcement.mdc", result.stdout)
        self.assertIn("remove  reflect-enforcement block", result.stdout)

    def test_off_leaves_a_users_own_cursor_rule_alone(self):
        os.makedirs(os.path.dirname(self.cursor_rule()))
        with open(self.cursor_rule(), "w", encoding="utf-8") as handle:
            handle.write("mine\n")
        self.install("0")
        self.assertEqual(read(self.cursor_rule()), "mine\n")

    def test_install_tests_never_write_the_checkouts_rule(self):
        path = os.path.join(REPO_ROOT, "engine", "reflect-enforcement.local.md")
        before = os.stat(path).st_mtime_ns if os.path.exists(path) else None
        self.install("1")
        after = os.stat(path).st_mtime_ns if os.path.exists(path) else None
        self.assertEqual(before, after)

    def test_core_imports_the_generated_rule(self):
        self.assertIn("@reflect-enforcement.local.md", read(os.path.join(REPO_ROOT, "engine", "CLAUDE.core.md")).splitlines())

    def test_no_ungated_rule_file_tells_the_agent_to_invoke_automate_me(self):
        for rel in UNGATED_RULE_FILES:
            with self.subTest(rel=rel):
                self.assertNotIn("automate-me", read(os.path.join(REPO_ROOT, rel)))


if __name__ == "__main__":
    unittest.main()
