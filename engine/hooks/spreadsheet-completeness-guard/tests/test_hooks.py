import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import detect  # noqa: E402


class SpreadsheetCompletenessTests(unittest.TestCase):
    def test_blocks_completion_without_coverage_receipt(self):
        finding = detect.decide({"last_assistant_message": "The spreadsheet is complete and all competitors are populated."})
        self.assertIsNotNone(finding)
        self.assertEqual(finding.rule_id, "spreadsheet-completeness-guard.incomplete")

    def test_stays_silent_with_pass_receipt(self):
        finding = detect.decide({"last_assistant_message": "SPREADSHEET_COVERAGE: PASS — the workbook is complete."})
        self.assertIsNone(finding)

    def test_stays_silent_for_non_spreadsheet_completion(self):
        self.assertIsNone(detect.decide({"last_assistant_message": "The README edit is complete."}))

    def test_requests_bounded_retry_when_coverage_is_missing(self):
        finding = detect.decide({
            "last_assistant_message": "The spreadsheet is complete.",
            "spreadsheet_retry_count": 1,
        })
        self.assertIn("retry 2/3", finding.message)

    def test_keeps_blocking_after_three_failed_retries(self):
        finding = detect.decide({
            "last_assistant_message": "SPREADSHEET_COVERAGE: FAIL — the spreadsheet is complete.",
            "spreadsheet_retry_count": 3,
        })
        self.assertIn("after the bounded retry loop", finding.message)


if __name__ == "__main__":
    unittest.main()
