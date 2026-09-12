#!/usr/bin/env python3
"""Unit tests for self_retraction_scan.py, the reflect miner's offline scan.

Run: python3 -m unittest discover -s engine/skills/reflect/scripts/tests -v

The wrong-check-reflect hook asks the background judge instead of matching
phrasings. This scan stays text-only so mining historical transcripts needs no
model calls, and it carries the cases the scenario suite no longer pins.
"""
import os
import sys
import unittest

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS_DIR)

import self_retraction_scan  # noqa: E402


class TestFindAdmission(unittest.TestCase):
    def test_listed_admission_matches(self):
        self.assertIsNotNone(self_retraction_scan.find_admission("My mistake — the count was 12."))

    def test_unlisted_wording_matches_structurally(self):
        text = "Also: a claim I made earlier was wrong. I told you the slice was green."
        self.assertIsNotNone(self_retraction_scan.find_admission(text))

    def test_hypothetical_stays_clean(self):
        text = "If my earlier check was wrong we should redo it — want me to re-read the file?"
        self.assertIsNone(self_retraction_scan.find_admission(text))

    def test_product_blame_is_not_self_correction(self):
        text = "The test was wrong, not the code — the fixture asserted the old brand green."
        self.assertIsNone(self_retraction_scan.find_admission(text))

    def test_quoted_admission_does_not_fire(self):
        text = 'The rule says "my earlier check was wrong" is an admission.'
        self.assertIsNone(self_retraction_scan.find_admission(text))


class TestScanAssistantTexts(unittest.TestCase):
    def test_collects_one_hit_per_admission(self):
        hits = self_retraction_scan.scan_assistant_texts(
            ["My mistake — the count was 12.", "The migration finished.", "I misread that file."]
        )
        self.assertEqual(len(hits), 2)

    def test_empty_input_yields_no_hits(self):
        self.assertEqual(self_retraction_scan.scan_assistant_texts(["", None]), [])


if __name__ == "__main__":
    unittest.main()
