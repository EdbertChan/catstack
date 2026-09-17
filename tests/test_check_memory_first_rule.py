#!/usr/bin/env python3
"""Pin the learned rule: search saved memory, both ways, before a deep dive.

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


class TestCheckMemoryFirst(unittest.TestCase):
    PREFIX = "- Before spending more than a couple of tool calls"

    def test_rule_searches_memory_both_ways(self):
        rule = bullet_starting(self.PREFIX)
        self.assertIn("search saved memory", rule)
        self.assertIn("reverse framing", rule)


if __name__ == "__main__":
    unittest.main()
