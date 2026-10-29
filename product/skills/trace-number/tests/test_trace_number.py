from __future__ import annotations

import contextlib
import csv
import io
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import trace_number as t  # noqa: E402

NOW = datetime(2026, 10, 2, 0, 0, 0, tzinfo=timezone.utc)
QUERY = '@ci.job.name:"build-app (dev)" status:error'
REPO = Path(__file__).resolve().parents[4]


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = t.main(argv, now=NOW)
    return rc, out.getvalue(), err.getvalue()


class Positive(unittest.TestCase):
    def test_rule_inventory_includes_trace_number(self):
        inventory = REPO / "engine" / "runbook" / "rules.tsv"
        with inventory.open(encoding="utf-8", newline="") as handle:
            rule_ids = {row["rule_id"] for row in csv.DictReader(handle, delimiter="\t")}
        self.assertIn("trace-number", rule_ids)

    def test_url_has_encoded_query_and_ms_window(self):
        rc, out, err = run([QUERY, "--from", "2026-10-01T00:00:00Z", "--to", "2026-10-02T00:00:00Z"])
        self.assertEqual(rc, 0, err)
        self.assertIn(f"query={quote(QUERY, safe='')}", out)
        self.assertIn("from_ts=1790812800000", out)
        self.assertIn("to_ts=1790899200000", out)
        self.assertIn("https://app.datadoghq.com/logs?", out)

    def test_relative_window_is_measured_from_now(self):
        lo, hi = t.parse_window("24h", "now", NOW)
        self.assertEqual(t.to_ms(hi) - t.to_ms(lo), 24 * 3600 * 1000)
        self.assertEqual(hi, NOW)

    def test_table_has_all_columns(self):
        rc, out, _ = run([QUERY, "--from", "7d", "--seen", "1,234", "--source", "tile A"])
        self.assertEqual(rc, 0)
        for col in t.COLUMNS:
            self.assertIn(col, out)
        self.assertIn("| tile A |", out)
        self.assertIn("1,234", out)


class Negative(unittest.TestCase):
    def test_unparseable_window_fails_and_prints_no_url(self):
        rc, out, err = run([QUERY, "--from", "last tuesday-ish"])
        self.assertNotEqual(rc, 0)
        self.assertIn("cannot parse time", err)
        self.assertNotIn("http", out)

    def test_backwards_window_fails_and_prints_no_url(self):
        rc, out, err = run([QUERY, "--from", "now", "--to", "24h"])
        self.assertNotEqual(rc, 0)
        self.assertIn("not before", err)
        self.assertNotIn("http", out)

    def test_empty_query_fails(self):
        rc, out, err = run(["  ", "--from", "24h"])
        self.assertNotEqual(rc, 0)
        self.assertNotIn("http", out)


if __name__ == "__main__":
    unittest.main()
