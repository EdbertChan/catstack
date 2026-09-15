#!/usr/bin/env python3
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS_DIR)

import spend_ledger_report

SCRIPT = os.path.join(SCRIPTS_DIR, "spend_ledger_report.py")
FIXTURE = os.path.join(SCRIPTS_DIR, "tests", "fixtures", "spend_ledger_report.json")


def load_fixture():
    with open(FIXTURE, encoding="utf-8") as handle:
        return json.load(handle)


class SpendLedgerReport(unittest.TestCase):
    def test_top_10_are_ranked_by_spend(self):
        data = spend_ledger_report.prepare_report_data(load_fixture())
        self.assertEqual(len(data["top_sessions"]), 10)
        costs = [session["cost_total"] for session in data["top_sessions"]]
        self.assertEqual(costs, sorted(costs, reverse=True))
        self.assertEqual(data["top_sessions"][0]["session"], "whale-17456079-input")
        self.assertNotIn("session-011-not-top", [session["session"] for session in data["top_sessions"]])

    def test_every_scanned_session_is_searchable_and_selectable(self):
        ledger = load_fixture()
        data = spend_ledger_report.prepare_report_data(ledger)
        page = spend_ledger_report.render_html(ledger)
        self.assertEqual(len(data["sessions"]), len(ledger["sessions"]))
        self.assertIn('id="session-search"', page)
        self.assertIn('id="session-select"', page)
        self.assertEqual(page.count("class='session-row'"), len(ledger["sessions"]))
        self.assertEqual(len(re.findall(r"<option value=", page)), len(ledger["sessions"]))
        self.assertIn("session-missing-token-total", page)

    def test_high_spend_timeline_keeps_ordered_raw_utc_and_deltas(self):
        data = spend_ledger_report.prepare_report_data(load_fixture())
        whale = data["top_sessions"][0]
        stamps = [event["timestamp_utc"] for event in whale["activity"] if event["timestamp_utc"]]
        parsed = [datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00")) for stamp in stamps]
        self.assertEqual(parsed, sorted(parsed))
        checkpoint = [event for event in whale["activity"] if event["label"] == "large cache-read checkpoint"][0]
        self.assertEqual(checkpoint["token_delta"]["cache_read"], 17_456_079)
        self.assertEqual(checkpoint["cumulative_tokens"]["cache_read"], 17_456_079)
        labels = [event["label"] for event in whale["activity"]]
        self.assertIn("repeat", labels)
        self.assertIn("waiting", labels)

    def test_missing_and_unscanned_states_are_explicit(self):
        data = spend_ledger_report.prepare_report_data(load_fixture())
        self.assertEqual(data["unchecked_hosts"][0]["name"], "fleet-missing")
        missing = [session for session in data["sessions"] if session["session"] == "session-missing-token-total"][0]
        self.assertEqual(missing["activity"][0]["kind"], "token_checkpoint_missing")
        self.assertEqual(missing["activity"][0]["missing"], ["timestamp", "token_usage"])
        no_activity = [session for session in data["sessions"] if session["session"] == "session-088"][0]
        self.assertEqual(no_activity["activity"][0]["kind"], "activity_missing")
        self.assertEqual(no_activity["activity"][0]["missing"], ["activity", "timestamp"])
        page = spend_ledger_report.render_html(load_fixture())
        self.assertIn("fleet-missing", page)
        self.assertIn("timed out after 900s", page)
        self.assertIn("missing: activity, timestamp", page)

    def test_render_is_self_contained_and_deterministic(self):
        ledger = load_fixture()
        first = spend_ledger_report.render_html(ledger)
        second = spend_ledger_report.render_html(ledger)
        self.assertEqual(first, second)
        self.assertNotIn("https://", first)
        self.assertIn("<script type=\"application/json\" id=\"ledger-data\">", first)
        self.assertIn("@media print", first)

    def test_cli_writes_report_and_fails_loudly_for_bad_input(self):
        folder = tempfile.mkdtemp(prefix="spend-ledger-report-")
        out = os.path.join(folder, "report.html")
        proc = subprocess.run([sys.executable, SCRIPT, FIXTURE, "--out", out], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("top 10 entries: 10", proc.stdout)
        with open(out, encoding="utf-8") as handle:
            page = handle.read()
        self.assertIn("<title>Spend Ledger Session Mining</title>", page)
        bad = os.path.join(folder, "bad.json")
        with open(bad, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        bad_proc = subprocess.run([sys.executable, SCRIPT, bad, "--out", os.path.join(folder, "bad.html")],
                                  capture_output=True, text=True)
        self.assertEqual(bad_proc.returncode, 2)
        self.assertIn("cannot read ledger", bad_proc.stderr)

    def test_help_prints_usage(self):
        proc = subprocess.run([sys.executable, SCRIPT, "--help"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Usage", proc.stdout)


if __name__ == "__main__":
    unittest.main()
