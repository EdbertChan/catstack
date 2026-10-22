#!/usr/bin/env python3
"""Evidence shapes the claim check has to accept as evidence.

Each case is a reply that carries real evidence in a shape the earlier
patterns did not read, paired with a reply that carries none and must still
fire.
"""
import os
import sys
import unittest

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LLM_JUDGE_DIR = os.path.join(os.path.dirname(HOOKS_DIR), "llm-judge")
sys.path.insert(0, LLM_JUDGE_DIR)
sys.path.insert(0, os.path.join(os.path.dirname(HOOKS_DIR), "_markers"))
sys.path.insert(0, HOOKS_DIR)

import claude_stop_check  # noqa: E402


class MultiDotFilenameCitation(unittest.TestCase):
    """A file name with more than one dot, cited with the ref it was read at."""

    CITED = (
        "The setup already runs before the build, because the job's "
        "before_script calls it at xmm3.gitlab-ci.yml:1563 @ origin/main."
    )

    def test_multi_dot_citation_with_ref_is_evidence_and_stays_silent(self):
        self.assertTrue(claude_stop_check.CITATION_REF_RE.search(self.CITED))
        self.assertIsNone(claude_stop_check.find_unverified_claim(self.CITED, ""))

    def test_multi_dot_file_line_is_read_as_a_citation(self):
        match = claude_stop_check.FILE_LINE_RE.search("see xmm3.gitlab-ci.yml:1563 for it")
        self.assertIsNotNone(match)
        self.assertEqual(match.group(0), "xmm3.gitlab-ci.yml:1563")

    def test_bare_because_with_no_evidence_still_fires(self):
        message = "The setup already runs before the build, because the job declares it."
        self.assertEqual(claude_stop_check.find_unverified_claim(message, ""), "because")


class BacktickedCitationWithRef(unittest.TestCase):
    def test_backticked_multi_dot_citation_with_ref_stays_silent(self):
        message = (
            "Today the build cannot start until rx finishes, because rx is in "
            "its `needs` (`xmm3.gitlab-ci.yml:1563 @ origin/main`)."
        )
        self.assertIsNone(claude_stop_check.find_unverified_claim(message, ""))


class PastedJsonKeyValueOutput(unittest.TestCase):
    """A tool's JSON reply pasted beside the claim is output, not a name."""

    def test_inline_json_key_value_output_silences_the_claim(self):
        message = (
            "Xirp has no outside command to open a file in its editor: the "
            "editor command is empty (`chirp:editorCommand:get` returned "
            '`"command": ""`) and the link setting is on (`"enabled": true`).'
        )
        self.assertIsNone(claude_stop_check.find_unverified_claim(message, ""))

    def test_fenced_json_key_value_output_counts_as_output(self):
        body = '{ "type": "chirp:terminalLinkEditor", "enabled": true }'
        self.assertTrue(claude_stop_check.OUTPUT_SHAPE_RE.search('  "enabled": true'))
        self.assertTrue(claude_stop_check.OUTPUT_SHAPE_RE.search('"command": ""'))
        message = (
            "The link setting is on, because the app says so (`chirp:get`).\n\n"
            "```\n" + body + "\n```"
        )
        self.assertIsNone(claude_stop_check.find_unverified_claim(message, ""))

    def test_backticked_name_with_no_json_value_still_fires(self):
        message = "Xirp has no outside command to open a file (`chirp:editorCommand:get`)."
        self.assertEqual(claude_stop_check.find_unverified_claim(message, ""), "has no")


class ColonIntroducesItsEvidence(unittest.TestCase):
    """A paragraph that ends in a colon and the block right after it are one unit."""

    FENCE = (
        "```\n"
        "$ xirp api send chirp:editorCommand:get\n"
        '  { "type": "chirp:editorCommand", "command": "" }\n'
        "```"
    )

    def test_colon_then_output_fence_after_a_blank_line_stays_silent(self):
        message = "Xirp has no outside command to open a file. I checked:\n\n" + self.FENCE
        self.assertIsNone(claude_stop_check.find_unverified_claim(message, ""))

    def test_colon_then_output_fence_on_the_next_line_stays_silent(self):
        message = "Xirp has no outside command to open a file. I checked:\n" + self.FENCE
        self.assertIsNone(claude_stop_check.find_unverified_claim(message, ""))

    def test_colon_then_list_of_cited_lines_stays_silent(self):
        message = (
            "There is no single setup line. It is two places:\n\n"
            "1. Job prep at `xmm3.gitlab-ci.yml:3408 @ origin/main`.\n"
            "2. The thin_uefi build at `xmm3-image-packager.sh:10 @ origin/main`."
        )
        self.assertIsNone(claude_stop_check.find_unverified_claim(message, ""))

    def test_no_colon_before_the_fence_still_fires(self):
        message = "Xirp has no outside command to open a file.\n\n" + self.FENCE
        self.assertEqual(claude_stop_check.find_unverified_claim(message, ""), "has no")

    def test_colon_then_plain_list_with_no_evidence_still_fires(self):
        message = (
            "There is no single setup line. It is two places:\n\n"
            "1. Job prep.\n"
            "2. The thin_uefi build."
        )
        self.assertEqual(claude_stop_check.find_unverified_claim(message, ""), "There is no")

    def test_colon_then_fence_does_not_silence_a_claim_after_the_fence(self):
        message = "I checked:\n" + self.FENCE + "\nIt broke because the cache was stale."
        self.assertEqual(claude_stop_check.find_unverified_claim(message, ""), "because")


if __name__ == "__main__":
    unittest.main()
