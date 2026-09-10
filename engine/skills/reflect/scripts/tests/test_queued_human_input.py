"""Behavior regressions for queued corrections and unclassifiable transcripts."""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import token_audit
import transcript_provenance


class TestQueuedHumanInput(unittest.TestCase):
    def audit(self, rows, harness="claude"):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "session.jsonl")
            with open(path, "w") as handle:
                for row in rows:
                    handle.write(json.dumps(row) + "\n")
            output = io.StringIO()
            with redirect_stdout(output):
                result = getattr(token_audit, "audit_" + harness)(path)
            return result, output.getvalue()

    @staticmethod
    def queued(text, **extra):
        return {"type": "queue-operation", "operation": "enqueue",
                "timestamp": "2026-09-09T01:00:00Z", "content": text, **extra}

    @staticmethod
    def user(text):
        return {"type": "user", "message": {"role": "user", "content": text}}

    def test_queue_correction_increases_intervention_count_from_zero_to_one(self):
        ordinary = [self.user("Please inspect the parser.")]
        before, _ = self.audit(ordinary)
        after, _ = self.audit(ordinary + [self.queued("I told you to add a test")])
        def intervention(result):
            return next(f for f in result["flags"] if f["name"] == "intervention-must-automate")
        self.assertEqual(intervention(before)["count"], 0)
        self.assertEqual(intervention(after)["count"], 1)
        self.assertEqual(after["frustration"]["n_user_messages"], 2)
        self.assertEqual(after["frustration"]["count"], 1)

    def test_repeated_queued_corrections_trigger_automation(self):
        result, _ = self.audit([self.queued("I told you to add a test"),
                                self.queued("I told you to run that test")])
        flags = {f["name"]: f for f in result["flags"]}
        self.assertEqual(flags["intervention-must-automate"]["value"], "yes")
        self.assertEqual(flags["intervention-must-automate"]["count"], 2)

    def test_ordinary_rows_keep_existing_counts_and_report_shape(self):
        result, _ = self.audit([self.user("I told you to add a test")])
        self.assertEqual(result["frustration"], {
            "count": 1, "n_user_messages": 1, "interruptions": 0,
            "kinds": {"told-you": 1}, "peak_window": None,
            "flagged": [{"index": 0, "ts": None, "kinds": ["told-you"],
                         "excerpt": "I told you to add a test"}],
        })
        flags = {f["name"]: f for f in result["flags"]}
        self.assertEqual(flags["frustration-signals"]["value"], "yes")
        self.assertEqual(flags["intervention-must-automate"]["value"], "no")
        self.assertEqual(flags["intervention-must-automate"]["count"], 1)

    def test_queue_operations_preserve_provenance_and_ignore_dequeue(self):
        rows = [self.user("Please inspect the parser.")]
        rows += [self.queued("I told you to add a test", **extra) for extra in (
            {"operation": "dequeue"}, {"isMeta": True}, {"agentId": "child"},
        )]
        rows.append(self.queued("<system-reminder>I told you to add a test</system-reminder>"))
        result, _ = self.audit(rows)
        self.assertEqual(result["frustration"]["n_user_messages"], 1)
        self.assertEqual(result["frustration"]["count"], 0)

    def test_unclassifiable_human_rows_are_unchecked_in_all_harnesses(self):
        fixtures = {
            "claude": [{"type": "user", "message": {"role": "user", "content": [
                {"type": "text", "text": "I told you to add a test"}]}}],
            "codex": [{"type": "response_item", "payload": {"type": "message", "role": "user",
                "content": [{"type": "input_text", "text": "I told you to add a test"}]}}],
            "cursor": [{"role": "user", "message": {"content": "I told you to add a test"}}],
            "omp": [{"type": "message", "message": {"role": "user", "content": []}}],
        }
        for harness, rows in fixtures.items():
            with self.subTest(harness=harness):
                result, output = self.audit(rows, harness)
                self.assert_unchecked(result, output)

    def assert_unchecked(self, result, output):
        flags = {f["name"]: f for f in result["flags"]}
        for name in ("frustration-signals", "intervention-must-automate"):
            self.assertEqual(flags[name]["value"], "unchecked")
            self.assertIsNone(flags[name]["count"])
            self.assertIn("no classifiable human rows", flags[name]["rationale"])
        self.assertIsNone(result["frustration"]["count"])
        self.assertIn("frustration-signals: unchecked", output)
        self.assertIn("intervention-must-automate: unchecked", output)
        self.assertNotIn("frustration-flagged user messages: 0/0", output)
        self.assertNotIn("intervention-must-automate: no", output)

    def test_empty_and_malformed_human_content_are_unchecked(self):
        for rows in ([], [self.user("")], [self.queued({"unsupported": "text"})]):
            with self.subTest(rows=rows):
                self.assert_unchecked(*self.audit(rows))

    def test_queue_support_does_not_change_other_parser_consumers(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl") as handle:
            handle.write(json.dumps(self.queued("I told you to add a test")) + "\n")
            handle.flush()
            self.assertEqual(transcript_provenance.direct_human_utterances(handle.name, "claude"), [])

    def test_invalid_json_is_unchecked_and_unreadable_input_is_an_error(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "session.jsonl")
            with open(path, "w") as handle:
                handle.write('{"type": "user",\n')
            output = io.StringIO()
            with redirect_stdout(output):
                result = token_audit.audit_claude(path)
            self.assert_unchecked(result, output.getvalue())
            # Failure to open the transcript must propagate, never return a clean report.
            os.unlink(path)
            with self.assertRaises(OSError):
                token_audit.audit_claude(path)

    def test_unchecked_survives_json_report_serialization(self):
        for harness in ("claude", "codex", "omp"):
            with self.subTest(harness=harness), tempfile.TemporaryDirectory() as root:
                path = os.path.join(root, "session.jsonl")
                out = os.path.join(root, "report.json")
                with open(path, "w"):
                    pass
                output = io.StringIO()
                with redirect_stdout(output):
                    getattr(token_audit, "audit_" + harness)(path, out_path=out)
                with open(out) as handle:
                    report = json.load(handle)
                self.assert_unchecked(report, output.getvalue())


if __name__ == "__main__":
    unittest.main()
