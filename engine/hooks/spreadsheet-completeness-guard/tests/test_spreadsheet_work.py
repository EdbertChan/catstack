import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import detect  # noqa: E402

SHEETS_CALL = {"type": "tool_use", "name": "mcp__claude_ai_Google_Sheets__update_values",
               "input": {"spreadsheetId": "abc", "range": "Raw!A1"}}
CSV_WRITE = {"type": "tool_use", "name": "Write",
             "input": {"file_path": "/tmp/out/competitors.csv", "content": "a,b\n"}}
BASH_ONLY = {"type": "tool_use", "name": "Bash",
             "input": {"command": "grep -n 'Setup LAGVM' xmm3.gitlab-ci.yml"}}
CODEX_XLSX = {"type": "function_call", "name": "shell",
              "arguments": json.dumps({"command": ["python3", "-c", "wb.save('model.xlsx')"]})}


class SpreadsheetWorkInTranscript(unittest.TestCase):
    def transcript(self, *blocks):
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, True)
        path = os.path.join(directory, "session.jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": "user", "message": {"content": "go"}}) + "\n")
            for block in blocks:
                if block.get("type") == "function_call":
                    handle.write(json.dumps({"type": "response_item", "payload": block}) + "\n")
                else:
                    handle.write(json.dumps({"type": "assistant", "message": {"content": [block]}}) + "\n")
        return path

    def test_populated_sheet_with_a_sheets_tool_call_still_fires(self):
        finding = detect.decide({
            "last_assistant_message": "The Google Sheet is populated with every competitor row. Done.",
            "transcript_path": self.transcript(BASH_ONLY, SHEETS_CALL),
        })
        self.assertIsNotNone(finding)
        self.assertEqual(finding.rule_id, detect.RULE_INCOMPLETE)

    def test_written_csv_counts_as_spreadsheet_work(self):
        finding = detect.decide({
            "last_assistant_message": "The spreadsheet is complete.",
            "transcript_path": self.transcript(CSV_WRITE),
        })
        self.assertIsNotNone(finding)

    def test_codex_shell_call_saving_an_xlsx_counts(self):
        finding = detect.decide({
            "last_assistant_message": "The workbook is ready.",
            "transcript_path": self.transcript(CODEX_XLSX),
        })
        self.assertIsNotNone(finding)

    def test_chart_and_done_with_no_spreadsheet_work_stays_silent(self):
        message = 'The chart row "Fix 1 and 2" draws that overlap. Done.'
        self.assertIsNone(detect.decide({
            "last_assistant_message": message,
            "transcript_path": self.transcript(BASH_ONLY),
        }))

    def test_bare_chart_is_not_spreadsheet_vocabulary(self):
        self.assertFalse(detect.claims_completion("The chart is done."))

    def test_spreadsheet_words_with_no_sheet_tool_call_stay_silent(self):
        self.assertIsNone(detect.decide({
            "last_assistant_message": "The spreadsheet is complete.",
            "transcript_path": self.transcript(BASH_ONLY),
        }))

    def test_no_transcript_is_reported_unchecked_not_blocked(self):
        event = {"last_assistant_message": "The spreadsheet is complete."}
        self.assertEqual(detect.detect(event), [])
        unchecked = event.get("_catstack_unchecked_findings")
        self.assertEqual([f.rule_id for f in unchecked], [detect.RULE_UNCHECKED])

    def test_unreadable_transcript_is_reported_unchecked_not_blocked(self):
        event = {"last_assistant_message": "The spreadsheet is complete.",
                 "transcript_path": "/no/such/session.jsonl"}
        self.assertEqual(detect.detect(event), [])
        self.assertEqual([f.rule_id for f in event["_catstack_unchecked_findings"]], [detect.RULE_UNCHECKED])

    def test_pass_receipt_stays_silent_without_reading_the_transcript(self):
        event = {"last_assistant_message": "SPREADSHEET_COVERAGE: PASS - the workbook is complete."}
        self.assertEqual(detect.detect(event), [])
        self.assertNotIn("_catstack_unchecked_findings", event)


if __name__ == "__main__":
    unittest.main()
