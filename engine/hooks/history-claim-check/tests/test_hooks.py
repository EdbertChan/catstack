"""Positive and negative fixtures for history-claim-check."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from detect import decide, is_publication, unsourced_claims  # noqa: E402

PUBLISH = " ".join(["gh", "pr", "create", "--title", "x", "--body-file"])
PATCH = " ".join(["gh", "api", "-X", "PATCH", "repos/o/r/pulls/1", "--body"])

BAD = """## Summary

The file stayed stale for roughly five months while every install reported
success. Three separate reflect passes found this and none fixed it.
It was written by an agent.
"""

GOOD = """## Correction

The window was 24 days, not five months:

```
$ git log --all -S 'link_item' --format='%ad %h' --date=short
2026-08-16 ca2f031
```

One pass found it, not three. The file was written by a human:

```
$ git log --format='%an' -- CLAUDE.md | sort -u
Edbert Chan
```
"""


class TestFires(unittest.TestCase):
    def test_catches_all_three_shipped_claims(self):
        kinds = " ".join(unsourced_claims(BAD))
        self.assertIn("duration", kinds)
        self.assertIn("count", kinds)
        self.assertIn("authorship", kinds)

    def test_blocks_a_publication_carrying_them(self):
        with tempfile.TemporaryDirectory() as d:
            b = Path(d) / "b.md"
            b.write_text(BAD)
            msg = decide(f"{PUBLISH} {b}", d)
            self.assertIsNotNone(msg)
            self.assertIn("history-claim-check", msg)

    def test_blocks_the_gh_api_pulls_form(self):
        self.assertIsNotNone(decide(PATCH + ' "stale for five months"'))


class TestStaysSilent(unittest.TestCase):
    def test_corrected_body_passes(self):
        self.assertEqual(unsourced_claims(GOOD), [])

    def test_publication_with_evidence_is_allowed(self):
        with tempfile.TemporaryDirectory() as d:
            b = Path(d) / "b.md"
            b.write_text(GOOD)
            self.assertIsNone(decide(f"{PUBLISH} {b}", d))

    def test_non_publication_command_is_untouched(self):
        self.assertFalse(is_publication("git commit -m 'stale for five months'"))
        self.assertIsNone(decide("git commit -m 'written by an agent'"))

    def test_unverified_prefix_is_accepted(self):
        self.assertEqual(unsourced_claims("UNVERIFIED: stale for five months"), [])

    def test_empty_and_malformed_do_not_raise(self):
        self.assertIsNone(decide(""))
        self.assertIsNone(decide(PUBLISH + ' "unclosed'))


if __name__ == "__main__":
    unittest.main()
