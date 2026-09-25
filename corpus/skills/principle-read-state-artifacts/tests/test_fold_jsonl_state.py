"""Tests for the fold_jsonl_state ledger digest script."""
import io
import json
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "fold_jsonl_state.py"
sys.path.insert(0, str(SCRIPT.parent))
import fold_jsonl_state as fold_mod


def write_ledger(tmp: str, rows: list[str]) -> Path:
    path = Path(tmp) / "ledger.jsonl"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


class TestFold(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_latest_row_per_group_wins(self):
        rows = [
            {"pr": 1, "kind": "k", "key": "a", "epoch": 100, "state": "old"},
            {"pr": 1, "kind": "k", "key": "a", "epoch": 200, "state": "new"},
            {"pr": 1, "kind": "k", "key": "b", "epoch": 50, "state": "b-state"},
        ]
        groups = fold_mod.fold(rows, ["pr", "kind", "key"], "epoch")
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[(1, "k", "a")]["state"], "new")
        self.assertEqual(groups[(1, "k", "b")]["state"], "b-state")

    def test_tie_keeps_later_input_row(self):
        rows = [
            {"pr": 1, "key": "a", "epoch": 100, "state": "first"},
            {"pr": 1, "key": "a", "epoch": 100, "state": "second"},
        ]
        groups = fold_mod.fold(rows, ["pr", "key"], "epoch")
        self.assertEqual(groups[(1, "a")]["state"], "second")

    def test_missing_order_field_falls_back_to_line_order(self):
        rows = [
            {"pr": 1, "key": "a", "state": "early"},
            {"pr": 1, "key": "a", "state": "late"},
        ]
        groups = fold_mod.fold(rows, ["pr", "key"], "epoch")
        self.assertEqual(groups[(1, "a")]["state"], "late")

    def test_malformed_lines_skipped_and_counted(self):
        path = write_ledger(self.tmp.name, [
            '{"pr": 1, "key": "a", "epoch": 1}',
            "not json at all",
            '{"pr": 2, "key": "b", "epoch": 2}',
        ])
        rows, bad = fold_mod.load_rows(path)
        self.assertEqual((len(rows), bad), (2, 1))

    def test_text_output_groups_and_folds(self):
        path = write_ledger(self.tmp.name, [
            '{"pr": 1, "key": "a", "epoch": 1, "state": "old"}',
            '{"pr": 1, "key": "a", "epoch": 2, "state": "new"}',
            '{"pr": 2, "key": "b", "epoch": 1, "state": "only"}',
        ])
        out = io.StringIO()
        with redirect_stdout(out):
            rc = fold_mod.main([str(path), "--by", "pr,key"])
        self.assertEqual(rc, 0)
        lines = out.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("state=new", lines[0])
        self.assertNotIn("state=old", out.getvalue())
        self.assertIn("state=only", lines[1])

    def test_json_output_one_object_per_group(self):
        path = write_ledger(self.tmp.name, [
            '{"pr": 1, "key": "a", "epoch": 1, "state": "x"}',
            '{"pr": 2, "key": "b", "epoch": 1, "state": "y"}',
        ])
        out = io.StringIO()
        with redirect_stdout(out):
            rc = fold_mod.main([str(path), "--by", "pr,key", "--json"])
        self.assertEqual(rc, 0)
        objs = [json.loads(l) for l in out.getvalue().strip().splitlines()]
        self.assertEqual([o["pr"] for o in objs], [1, 2])
        self.assertEqual(objs[0]["state"], "x")

    def test_missing_ledger_exits_nonzero(self):
        err = io.StringIO()
        with redirect_stderr(err):
            rc = fold_mod.main(["/nonexistent/x.jsonl", "--by", "pr"])
        self.assertEqual(rc, 1)
        self.assertIn("not found", err.getvalue())

    def test_no_subprocess_calls(self):
        """The fold is read-only: it must never spawn a subprocess."""
        path = write_ledger(self.tmp.name, ['{"pr": 1, "epoch": 1}'])
        with unittest.mock.patch.object(subprocess, "Popen", side_effect=AssertionError("subprocess spawned")):
            with redirect_stdout(io.StringIO()):
                rc = fold_mod.main([str(path), "--by", "pr"])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
