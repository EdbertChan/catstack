#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import tempfile
import unittest

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(SCRIPTS_DIR, "render_spend_report.py")


def row(tool, host, kind, cost, priced="list", waiting=0.0, repeat=0.0, tokens=None, day="2026-09-01"):
    return {"tool": tool, "host": host, "session": f"{tool}-{host}-{kind}-{cost}", "repo": "app", "kind": kind,
            "model": "claude-sonnet-5", "originator": "", "priced": priced, "first": f"{day}T10:00:00+00:00",
            "last": f"{day}T12:00:00+00:00", "hours": 2.0, "calls": 10, "sub_calls": 1, "prompts": 3,
            "tokens": tokens or {"input": 1, "cache_write": 1, "cache_read": 1, "output": 1}, "peak_history": 250000,
            "cost": {}, "cost_total": cost, "sub_cost": 1.5, "polling": {"waiting": waiting, "repeat": repeat},
            "unpriced_calls": 0}


def render(ledger):
    folder = tempfile.mkdtemp(prefix="render-spend-")
    source = os.path.join(folder, "ledger.json")
    out = os.path.join(folder, "page.html")
    with open(source, "w", encoding="utf-8") as handle:
        json.dump(ledger, handle)
    proc = subprocess.run([sys.executable, SCRIPT, source, "--out", out], capture_output=True, text=True)
    page = ""
    if os.path.exists(out):
        with open(out, encoding="utf-8") as handle:
            page = handle.read()
    return proc, page


class RenderSpendReport(unittest.TestCase):
    def test_totals_polling_and_unchecked_host_are_on_the_page(self):
        ledger = {"generated_at": "2026-09-14T20:00:00+00:00", "days": 30, "hosts": [
            {"name": "local", "state": "checked", "reason": "", "status": {}, "sessions": 3},
            {"name": "box-2", "state": "unchecked", "reason": "timed out after 900s", "status": {}, "sessions": 0}],
            "sessions": [row("claude", "local", "typed", 120.0, waiting=6.0, repeat=4.0),
                         row("claude", "local", "invoker", 0.25),
                         row("codex", "local", "typed", 9.5, priced="estimate"),
                         row("invoker-agent-log", "local", "invoker", 0.0, priced="unpriced",
                             tokens={"input": 2_000_000_000, "cache_write": 0, "cache_read": 0, "output": 0})]}
        proc, page = render(ledger)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("<title>Agent Spend Dashboard</title>", page)
        self.assertIn("$120", page)
        self.assertIn("$10.00", page)
        self.assertIn("box-2", page)
        self.assertIn("Not scanned: timed out after 900s", page)
        self.assertIn("2.00B tokens have no price", page)
        self.assertIn("unchecked hosts: box-2", proc.stdout)

    def test_empty_ledger_says_so(self):
        proc, page = render({"days": 7, "hosts": [{"name": "local", "state": "checked", "reason": "", "status": {},
                                                   "sessions": 0}], "sessions": []})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("No sessions found in this window", page)

    def test_unreadable_ledger_fails_loudly(self):
        folder = tempfile.mkdtemp(prefix="render-spend-bad-")
        bad = os.path.join(folder, "bad.json")
        with open(bad, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        proc = subprocess.run([sys.executable, SCRIPT, bad, "--out", os.path.join(folder, "p.html")],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("cannot read ledger", proc.stderr)

    def test_help_prints_usage(self):
        proc = subprocess.run([sys.executable, SCRIPT, "--help"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Usage", proc.stdout)


if __name__ == "__main__":
    unittest.main()
