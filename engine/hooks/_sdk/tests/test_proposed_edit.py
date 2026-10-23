from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

SDK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SDK_DIR))

from finding import Finding
from proposed_edit import ProposedEdit


class ProposedEditTests(unittest.TestCase):
    def test_write_to_a_new_path_marks_every_line_as_edited(self):
        with tempfile.TemporaryDirectory() as directory:
            edit = ProposedEdit("Write", {"file_path": os.path.join(directory, "new.py"), "content": "a = 1\nb = 2\n"})
            self.assertTrue(edit.creates_file())
            self.assertTrue(edit.apply())
        self.assertEqual(edit.edited_lines, {1, 2})

    def test_edit_marks_only_the_replaced_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "module.py")
            Path(path).write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")
            edit = ProposedEdit("Edit", {"file_path": path, "old_string": "b = 2\n", "new_string": "b = 20\nb2 = 21\n"})
            self.assertTrue(edit.apply())
        self.assertEqual(edit.after, "a = 1\nb = 20\nb2 = 21\nc = 3\n")
        self.assertEqual(edit.edited_lines, {2, 3})

    def test_a_pure_deletion_marks_the_lines_around_the_gap(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "module.py")
            Path(path).write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")
            edit = ProposedEdit("Edit", {"file_path": path, "old_string": "b = 2\n", "new_string": ""})
            self.assertTrue(edit.apply())
        self.assertEqual(edit.edited_lines, {1, 2})

    def test_multiedit_applies_in_order_and_replace_all_hits_every_occurrence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "module.py")
            Path(path).write_text("x = 1\nx = 1\n", encoding="utf-8")
            edit = ProposedEdit(
                "MultiEdit",
                {"file_path": path, "edits": [{"old_string": "x", "new_string": "y", "replace_all": True}, {"old_string": "y = 1\n", "new_string": "y = 2\n"}]},
            )
            self.assertTrue(edit.apply())
        self.assertEqual(edit.after, "y = 2\ny = 1\n")

    def test_missing_file_for_an_edit_is_unchecked(self):
        with tempfile.TemporaryDirectory() as directory:
            edit = ProposedEdit("Edit", {"file_path": os.path.join(directory, "missing.py"), "old_string": "a", "new_string": "b"})
            self.assertFalse(edit.apply())
        self.assertIn("does not exist", edit.unchecked_reason)

    def test_old_string_not_in_file_is_unchecked(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "module.py")
            Path(path).write_text("a = 1\n", encoding="utf-8")
            edit = ProposedEdit("Edit", {"file_path": path, "old_string": "zzz", "new_string": "b"})
            self.assertFalse(edit.apply())
        self.assertIn("old_string was not found", edit.unchecked_reason)

    def test_from_event_ignores_other_tools_and_malformed_input(self):
        self.assertIsNone(ProposedEdit.from_event({"tool_name": "Bash", "tool_input": {"command": "ls"}}))
        self.assertIsNone(ProposedEdit.from_event({"tool_name": "Edit", "tool_input": "nope"}))
        self.assertIsNotNone(ProposedEdit.from_event({"tool_name": "Write", "tool_input": {"file_path": "/x.py", "content": ""}}))

    def test_attach_unchecked_records_the_finding_and_a_stderr_line(self):
        event: dict[str, object] = {}
        edit = ProposedEdit("Write", {"file_path": "/x.py", "content": ""})
        finding = Finding(rule_id="demo.unchecked", subject="/x.py", message="demo: not checked", evidence="")
        edit.attach_unchecked(event, finding)
        self.assertEqual(event["_catstack_unchecked_findings"], [finding])
        self.assertEqual(event["_catstack_stderr_lines"], ["demo: not checked"])


if __name__ == "__main__":
    unittest.main()
