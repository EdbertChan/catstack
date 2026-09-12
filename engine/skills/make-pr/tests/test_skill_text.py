#!/usr/bin/env python3
"""The fixture-vs-live gate names the tag every hook accepts.

Run: python3 -m unittest discover -s engine/skills/make-pr/tests -v
"""
import os
import sys
import unittest

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(SKILL_DIR)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))

import escape_hatch_vocab as vocab  # noqa: E402


class FixtureVsLiveGate(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(SKILL_DIR, "SKILL.md"), encoding="utf-8") as handle:
            self.text = handle.read()

    def test_unsettled_live_claims_use_the_tag(self):
        self.assertIn("{{CAT-UNVERIFIED: <claim> -- cannot verify: <reason>}}", self.text)

    def test_skill_never_tells_the_author_to_write_the_retired_marker(self):
        self.assertEqual(vocab.instructs_retired_marker(self.text), [])


if __name__ == "__main__":
    unittest.main()
