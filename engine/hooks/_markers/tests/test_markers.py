#!/usr/bin/env python3
"""Unit tests for the shared escape-hatch marker.

Run: python3 -m unittest discover -s engine/hooks/_markers/tests -v
"""
import os
import sys
import unittest

MARKERS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, MARKERS_DIR)

import markers  # noqa: E402

WELL_FORMED = "{{CAT-UNVERIFIED: the glob covers it -- cannot verify: no CI access from here}}"
NO_BLOCKER = "{{CAT-UNVERIFIED: the glob covers it}}"
EMPTY_BLOCKER = "{{CAT-UNVERIFIED: the glob covers it -- cannot verify:   }}"


class TagRecognition(unittest.TestCase):
    def test_tag_naming_a_blocker_is_well_formed(self):
        self.assertEqual(markers.well_formed_tags(WELL_FORMED), [WELL_FORMED])
        self.assertEqual(markers.malformed_tags(WELL_FORMED), [])

    def test_tag_naming_no_blocker_is_malformed(self):
        self.assertEqual(markers.well_formed_tags(NO_BLOCKER), [])
        self.assertEqual(markers.malformed_tags(NO_BLOCKER), [NO_BLOCKER])

    def test_blocker_with_only_whitespace_does_not_count(self):
        self.assertEqual(markers.well_formed_tags(EMPTY_BLOCKER), [])
        self.assertEqual(markers.malformed_tags(EMPTY_BLOCKER), [EMPTY_BLOCKER])

    def test_tag_is_case_insensitive_and_tolerates_inner_spaces(self):
        text = "{{ cat-unverified: x -- Cannot Verify: the box is offline }}"
        self.assertEqual(len(markers.well_formed_tags(text)), 1)

    def test_several_tags_are_each_classified(self):
        text = f"{WELL_FORMED}\n\n{NO_BLOCKER}"
        self.assertEqual(len(markers.well_formed_tags(text)), 1)
        self.assertEqual(len(markers.malformed_tags(text)), 1)


class ParagraphExcuse(unittest.TestCase):
    def test_well_formed_tag_excuses_its_paragraph(self):
        self.assertTrue(markers.excuses_paragraph(f"The job passes. {WELL_FORMED}"))

    def test_malformed_tag_does_not_excuse_its_paragraph(self):
        self.assertFalse(markers.excuses_paragraph(f"The job passes. {NO_BLOCKER}"))

    def test_clean_paragraph_is_not_excused(self):
        self.assertFalse(markers.excuses_paragraph("The job passes."))


class LegacyMarker(unittest.TestCase):
    def test_bare_marker_is_reported_as_legacy(self):
        self.assertTrue(markers.has_legacy_marker("UNVERIFIED: the glob covers it"))

    def test_bare_marker_never_excuses_a_paragraph(self):
        self.assertFalse(markers.excuses_paragraph("UNVERIFIED: the glob covers it"))

    def test_new_tag_is_not_reported_as_legacy(self):
        self.assertFalse(markers.has_legacy_marker(WELL_FORMED))

    def test_clean_text_has_no_legacy_marker(self):
        self.assertFalse(markers.has_legacy_marker("The job passes."))


class Messages(unittest.TestCase):
    def test_both_messages_show_the_literal_tag_template(self):
        self.assertIn("{{CAT-UNVERIFIED: <claim> -- cannot verify: <reason>}}", markers.MALFORMED_TAG_MESSAGE)
        self.assertIn("{{CAT-UNVERIFIED: <claim> -- cannot verify: <reason>}}", markers.LEGACY_MARKER_MESSAGE)

class RenderedMessagesKeepTheirBraces(unittest.TestCase):
    """Every hook that names the tag in a block message renders it with both
    braces intact.

    These messages are `.format()` templates. A literal `{{CAT-UNVERIFIED}}`
    written into one collapses to `{CAT-UNVERIFIED}` when it is rendered, and
    the hook then tells the author to type a tag that no hook recognises.
    That shipped once here and every existing test still passed, because they
    all asserted on the substring `CAT-UNVERIFIED`, which survives the
    collapse. These assert on the braces."""

    def test_external_claim_gate_renders_both_braces(self):
        sys.path.insert(0, os.path.join(os.path.dirname(MARKERS_DIR), "external-claim-gate"))
        import detect as external_detect  # noqa: PLC0415
        message = external_detect.block_message([
            external_detect.Finding(outcome="hit", destination="gh issue create",
                                    claim="because", detail="x"),
        ])
        self.assertIn(markers.TAG_TEMPLATE, message)

    def test_tag_template_itself_has_double_braces(self):
        self.assertTrue(markers.TAG_TEMPLATE.startswith("{{"))
        self.assertTrue(markers.TAG_TEMPLATE.endswith("}}"))

    def test_a_collapsed_tag_is_not_recognised(self):
        collapsed = markers.TAG_TEMPLATE.replace("{{", "{").replace("}}", "}")
        self.assertEqual(markers.well_formed_tags(collapsed), [])


if __name__ == "__main__":
    unittest.main()
