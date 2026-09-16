#!/usr/bin/env python3
"""Pin the learned rule: read a script's whole body before asking to run it.

A detector cannot judge this reliably, so the test proves the rule is present
with its trigger, required action, and reason; deleting or hollowing it fails here.
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


class TestReadScriptBeforeConsent(unittest.TestCase):
    PREFIX = "- Before asking me whether to run a script"

    def test_rule_requires_the_whole_body_not_the_header(self):
        rule = bullet_starting(self.PREFIX)
        self.assertIn("read its whole body", rule)
        self.assertIn("header comment", rule)
        self.assertIn("`--dry-run` output", rule)

    def test_rule_names_what_the_question_must_list(self):
        rule = bullet_starting(self.PREFIX)
        for effect in ("process it kills", "file it deletes", "service it restarts"):
            self.assertIn(effect, rule)


if __name__ == "__main__":
    unittest.main()
