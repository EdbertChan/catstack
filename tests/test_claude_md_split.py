#!/usr/bin/env python3
"""Guard the split between hand-written and reflect-learned global rules."""
import os
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(name):
    with open(os.path.join(REPO_ROOT, name)) as handle:
        return handle.read()


class TestClaudeMdSplit(unittest.TestCase):
    def test_root_only_assembles_imports(self):
        lines = read("CLAUDE.md").splitlines()
        self.assertIn("@engine/CLAUDE.core.md", lines)
        self.assertIn("@corpus/CLAUDE.learned.md", lines)
        self.assertFalse(any(line.startswith("- ") for line in lines))

    def test_core_has_no_learned_rules(self):
        self.assertNotIn("Found via `/reflect`", read("engine/CLAUDE.core.md"))

    def test_learned_has_learned_rules(self):
        self.assertIn("Found via `/reflect`", read("corpus/CLAUDE.learned.md"))

    def test_learned_headings_are_present_in_core(self):
        core = read("engine/CLAUDE.core.md")
        learned_headings = [
            line for line in read("corpus/CLAUDE.learned.md").splitlines()
            if line.startswith("#")
        ]
        for heading in learned_headings:
            self.assertIn(heading, core)
