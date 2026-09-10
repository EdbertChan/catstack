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


class TestSameLineWrite(unittest.TestCase):
    """The hook runs before the line does, so a body written by that line is unseen."""

    def _stale(self, d: str, text: str) -> Path:
        b = Path(d) / "b.md"
        b.write_text(text)
        return b

    def test_blocks_redirect_write_and_publish_in_one_line(self):
        with tempfile.TemporaryDirectory() as d:
            self._stale(d, GOOD)
            msg = decide("printf '%s\\n' 'stale for five months' > b.md && " + PUBLISH + " b.md", d)
            self.assertIsNotNone(msg)
            self.assertIn("same command", msg)
            self.assertIn("b.md", msg)

    def test_blocks_heredoc_write_and_publish_in_one_line(self):
        with tempfile.TemporaryDirectory() as d:
            self._stale(d, BAD)
            cmd = f"cat > b.md <<'EOF'\n{GOOD}EOF\n{PUBLISH} b.md"
            msg = decide(cmd, d)
            self.assertIsNotNone(msg)
            self.assertIn("same command", msg)
            self.assertNotIn("claim(s)", msg)

    def test_blocks_tee_pipeline_write_and_publish(self):
        with tempfile.TemporaryDirectory() as d:
            self._stale(d, GOOD)
            cmd = f"cat <<'EOF' | tee b.md >/dev/null\n{BAD}EOF\n{PUBLISH} b.md"
            self.assertIn("same command", decide(cmd, d) or "")

    def test_blocks_equals_form_and_moved_directory(self):
        with tempfile.TemporaryDirectory() as d:
            self._stale(d, GOOD)
            cmd = ("cat > /tmp/x/b.md <<'EOF'\nhi\nEOF\n"
                   "cd repo && gh pr edit 1 --body-file=../b.md")
            self.assertIn("same command", decide(cmd, d) or "")

    def test_blocks_gh_api_input_written_in_same_line(self):
        cmd = "echo '{}' > p.json; gh api -X PATCH repos/o/r/pulls/1 --input p.json"
        self.assertIn("same command", decide(cmd) or "")

    def test_body_written_in_an_earlier_call_blocks_as_today(self):
        with tempfile.TemporaryDirectory() as d:
            self._stale(d, BAD)
            msg = decide(f"{PUBLISH} b.md", d)
            self.assertIn("claim(s)", msg or "")
            self.assertNotIn("same command", msg or "")

    def test_body_written_in_an_earlier_call_passes_as_today(self):
        with tempfile.TemporaryDirectory() as d:
            self._stale(d, GOOD)
            self.assertIsNone(decide(f"{PUBLISH} b.md", d))

    def test_unrelated_write_in_same_line_is_not_refused(self):
        with tempfile.TemporaryDirectory() as d:
            self._stale(d, GOOD)
            self.assertIsNone(decide(f"echo hi > log.txt && {PUBLISH} b.md 2>&1", d))

    def test_stdin_body_file_is_checked_not_refused(self):
        self.assertIsNone(decide(f"{PUBLISH} - <<'EOF'\n{GOOD}EOF"))
        self.assertIn("claim(s)", decide(f"{PUBLISH} - <<'EOF'\n{BAD}EOF") or "")


class TestPublishIsAnExecutedProgram(unittest.TestCase):
    def test_publish_words_inside_a_string_are_not_publishing(self):
        for cmd in (
            "git commit -m 'teach gh pr create --body to be checked'",
            "echo 'gh pr edit 1 --body \"written by an agent\"'",
            'grep -rn "gh pr create" engine/',
            "rg 'repos/o/r/pulls' docs; ls create-pr.mjs.bak",
            "cat > notes.md <<'EOF'\ngh pr create --body 'stale for five months'\nEOF",
            "# gh pr create --body 'stale for five months'\nls",
        ):
            with self.subTest(cmd=cmd):
                self.assertFalse(is_publication(cmd))
                self.assertIsNone(decide(cmd))

    def test_detects_publish_at_every_executed_position(self):
        for cmd in (
            "gh pr create --title x",
            "cd repo && gh pr edit 7 --body y",
            "GH_TOKEN=t /usr/local/bin/gh pr create",
            "env -u GH_HOST command gh pr create",
            "url=$(gh pr create --title x)",
            'echo "$(gh pr edit 1 --body y)"',
            "bash -lc 'gh pr create --title x'",
            "if gh api repos/o/r/pulls/1 -X PATCH -f body=x; then :; fi",
            "node scripts/create-pr.mjs --body-file b.md",
            "./create-pr.mjs",
        ):
            with self.subTest(cmd=cmd):
                self.assertTrue(is_publication(cmd))

    def test_blocks_the_standard_heredoc_body_substitution(self):
        bad = f"{PUBLISH[:-len(' --body-file')]} --body \"$(cat <<'EOF'\nWe don't know.\n{BAD}EOF\n)\""
        good = f"{PUBLISH[:-len(' --body-file')]} --body \"$(cat <<'EOF'\nWe don't know.\n{GOOD}EOF\n)\""
        self.assertIn("claim(s)", decide(bad) or "")
        self.assertIsNone(decide(good))

    def test_malformed_line_is_treated_as_publishing(self):
        # Unparseable: shell would refuse it too, but the check falls back to the
        # old unanchored match rather than calling it clean.
        self.assertTrue(is_publication('gh pr create --title "x'))


if __name__ == "__main__":
    unittest.main()
