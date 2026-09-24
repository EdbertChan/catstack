#!/usr/bin/env python3
"""Pin the learned rule: anchor a Bash call's paths, never a previous call's cwd.

A detector cannot tell a deliberate relative path from a stale one, so the test
proves the rule is present with its mechanism, both failure shapes, and the
required action; deleting or hollowing it fails here.
"""
import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEARNED = os.path.join(REPO_ROOT, "corpus", "CLAUDE.learned.md")


def working_style_section():
    with open(LEARNED, encoding="utf-8") as handle:
        text = handle.read()
    start = text.index("# Working style")
    end = text.find("\n# ", start + 1)
    return text[start:] if end == -1 else text[start:end]


def bullet_starting(prefix):
    for line in working_style_section().splitlines():
        if line.startswith(prefix):
            return line
    raise AssertionError(f"no working-style rule starts with {prefix!r}")


class TestBashCwdAnchor(unittest.TestCase):
    PREFIX = "- A `cd` in one Bash call carries into the next call"

    def test_rule_names_both_halves_of_the_mechanism(self):
        rule = bullet_starting(self.PREFIX)
        self.assertIn("inside the session's working directory", rule)
        self.assertIn("outside it", rule)
        self.assertIn("only the reset case is announced", rule)

    def test_rule_names_the_same_message_shared_shell(self):
        rule = bullet_starting(self.PREFIX)
        self.assertIn("single message share that one shell", rule)

    def test_rule_names_both_observed_failure_shapes(self):
        rule = bullet_starting(self.PREFIX)
        self.assertIn("No such file or directory", rule)
        self.assertIn("can't open file", rule)
        self.assertIn("read as a missing file rather than as a wrong directory", rule)

    def test_rule_requires_anchoring_and_forbids_splitting_the_cd(self):
        rule = bullet_starting(self.PREFIX)
        self.assertIn('cd "$R"', rule)
        self.assertIn("pass an absolute path", rule)
        self.assertIn("never split a `cd` from the command that depends on it", rule)

    def test_rule_cites_pathname_resolution(self):
        rule = bullet_starting(self.PREFIX)
        self.assertIn("IEEE Std 1003.1-2017", rule)
        self.assertIn("does not begin with a slash", rule)


if __name__ == "__main__":
    unittest.main()
