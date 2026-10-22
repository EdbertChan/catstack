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


if __name__ == "__main__":
    unittest.main()
