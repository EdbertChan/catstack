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

    def test_false_positive_about_another_checker_stays_clean(self):
        text = "I'll note the guard's false positive on a read-only prompt as a backlog item."
        self.assertIsNone(self_retraction_scan.find_admission(text))

    def test_false_claim_still_matches(self):
        text = "My earlier claim was false; the real count is 12."
        self.assertIsNotNone(self_retraction_scan.find_admission(text))

    def test_external_artifact_blame_in_a_later_sentence_stays_clean(self):
        text = (
            "I did not add a repro. The rule already has regression coverage in the "
            "validator test file, asserting this exact error string - the validator "
            "behaved correctly; the branch contents were wrong."
        )
        self.assertIsNone(self_retraction_scan.find_admission(text))

    def test_own_prior_statement_blamed_in_a_later_sentence_still_matches(self):
        text = "I read the two files earlier and reported a total. That count was wrong."
        self.assertIsNotNone(self_retraction_scan.find_admission(text))

    def test_own_subject_with_a_trailing_prepositional_object_still_matches(self):
        text = "My earlier read of the config was wrong. The default is 4, not 8."
        self.assertIsNotNone(self_retraction_scan.find_admission(text))

    def test_own_count_of_a_third_party_thing_still_matches(self):
        text = "I told you the repo had 12 rules. My count of the files was wrong."
        self.assertIsNotNone(self_retraction_scan.find_admission(text))

    def test_third_party_blame_after_a_first_person_clause_stays_clean(self):
        text = "I re-read the fixture earlier, the fixture was wrong."
        self.assertIsNone(self_retraction_scan.find_admission(text))

    def test_third_party_blame_inside_a_reported_clause_stays_clean(self):
        text = "I read the report earlier and said the test was wrong."
        self.assertIsNone(self_retraction_scan.find_admission(text))

    def test_what_was_wrong_summary_heading_stays_clean(self):
        text = (
            "The fix is verified against the live PR body.\n\n"
            "## What was wrong and what I did\n\n"
            "The validate check runs a PR-body gate. It flags a changed file name."
        )
        self.assertIsNone(self_retraction_scan.find_admission(text))

    def test_interrogative_subject_wrong_stays_clean(self):
        text = "I traced why the build was wrong and pushed the reworded body."
        self.assertIsNone(self_retraction_scan.find_admission(text))

    def test_real_admission_beside_a_what_was_wrong_heading_still_matches(self):
        text = (
            "## What was wrong and what I did\n\n"
            "My earlier check was wrong; I re-read the file and the count is 12."
        )
        self.assertIsNotNone(self_retraction_scan.find_admission(text))


class TestEvidenceOrderIsOutOfReach(unittest.TestCase):
    """Two real corrections this scan cannot see, and the reason it cannot.

    Both are corrections about evidence ORDER: the claim was true, and it was
    asserted before the check ran. Nothing in either sentence says anything was
    wrong, so every pattern here misses them by construction. Pinned so the
    next author widens the regex knowingly rather than by accident: the catch
    for this class is the unverified-tag-ledger discharge transition, which
    reads state rather than wording.
    """

    def test_arming_the_implied_check_is_not_reachable_by_wording(self):
        text = "Correcting one claim and arming the check I implied:"
        self.assertIsNone(self_retraction_scan.find_admission(text))

    def test_right_but_asserted_early_is_not_reachable_by_wording(self):
        text = "I was right - but I said it a turn before I checked it"
        self.assertIsNone(self_retraction_scan.find_admission(text))

    def test_the_same_sentence_with_a_wrongness_word_does_fire(self):
        text = "I was wrong about the path; I said it a turn before I checked it."
        self.assertIsNotNone(self_retraction_scan.find_admission(text))


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
