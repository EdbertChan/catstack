from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "SKILL.md"
TESTS = ROOT / "tests"


class DiffReadGateTests(unittest.TestCase):
    def setUp(self):
        self.skill = SKILL.read_text()
        step4_match = re.search(
            r"## Step 4: Merge each stack, bottom-up(?P<body>.*?)## Step 5:",
            self.skill,
            re.S,
        )
        self.assertIsNotNone(step4_match, "Step 4 section is present")
        self.step4 = step4_match.group("body")

    def test_step4_requires_recorded_line_count_and_full_read_before_admin_merge(self):
        merge_index = self.step4.index("gh pr merge <pr>")
        pre_merge = self.step4[:merge_index]

        self.assertIn("Before any `gh pr merge --admin`", pre_merge)
        self.assertIn("gh pr diff", pre_merge)
        self.assertIn("> \"$diff_file\"", pre_merge)
        self.assertIn("wc -l", pre_merge)
        self.assertIn("nl -ba \"$diff_file\"", pre_merge)
        self.assertIn('test "$lines_read" = "$diff_lines"', pre_merge)
        self.assertIn("number of lines read equals the recorded total", pre_merge)

    def test_step4_documents_narrowed_reads_as_unchecked_not_reviewed(self):
        for command in ("head", "tail", "grep", "awk", "sed"):
            self.assertIn(f"`{command}`", self.step4)

        self.assertIn("mark that PR `unchecked`, never `reviewed`", self.step4)
        self.assertIn("may not report such a PR as reviewed", self.step4)

    def test_complete_read_fixture_marks_pr_reviewed(self):
        fixture = (TESTS / "fixture_complete_diff_read.md").read_text()

        self.assertIn("wc -l", fixture)
        self.assertIn("nl -ba", fixture)
        self.assertIn("lines_read=184", fixture)
        self.assertIn("Expected outcome: PR 42 may be reported as `reviewed`", fixture)

    def test_truncated_read_fixture_marks_pr_unchecked(self):
        fixture = (TESTS / "fixture_truncated_diff_read.md").read_text()
        fixture_lower = fixture.lower()

        self.assertIn("head -200", fixture)
        self.assertIn("diff_lines` value is 913", fixture)
        self.assertIn("PR 77 is `unchecked`, not `reviewed`", fixture)
        self.assertIn("operator may not\nreport pr 77 as reviewed", fixture_lower)


if __name__ == "__main__":
    unittest.main()
