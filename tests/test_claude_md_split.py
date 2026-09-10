#!/usr/bin/env python3
"""Guard the split between hand-written and reflect-learned global rules."""
import os
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MINED_BANNER = "Rules mined by reflect."


def read(name):
    with open(os.path.join(REPO_ROOT, name)) as handle:
        return handle.read()


class TestClaudeMdSplit(unittest.TestCase):
    def test_root_only_assembles_imports(self):
        lines = read("CLAUDE.md").splitlines()
        self.assertIn("@engine/CLAUDE.core.md", lines)
        self.assertIn("@corpus/CLAUDE.learned.md", lines)
        self.assertFalse(any(line.startswith("- ") for line in lines))

    def test_core_is_not_the_mined_file(self):
        core = read("engine/CLAUDE.core.md")
        self.assertNotIn(MINED_BANNER, core)
        core_lines = set(core.splitlines())
        for line in read("corpus/CLAUDE.learned.md").splitlines():
            if line.startswith("- "):
                self.assertNotIn(line, core_lines)

    def test_learned_declares_itself_mined(self):
        learned = read("corpus/CLAUDE.learned.md")
        self.assertTrue(learned.startswith(MINED_BANNER))
        self.assertTrue(any(line.startswith("- ") for line in learned.splitlines()))

    def test_neither_file_carries_provenance_narrative(self):
        for name in ("engine/CLAUDE.core.md", "corpus/CLAUDE.learned.md"):
            self.assertNotIn("Found via", read(name), f"{name} states rules, not where they came from")

    def test_learned_headings_are_present_in_core(self):
        core = read("engine/CLAUDE.core.md")
        learned_headings = [
            line for line in read("corpus/CLAUDE.learned.md").splitlines()
            if line.startswith("#")
        ]
        for heading in learned_headings:
            self.assertIn(heading, core)
