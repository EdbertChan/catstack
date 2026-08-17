#!/usr/bin/env python3
"""End-to-end token-audit tests against sample conversation fixtures.

These run the real token_audit CLI (subprocess) and the in-process API against
committed Claude Code–shaped JSONL under fixtures/. They lock the
recommendations reflect's Cost/Judgment lenses rely on: which flags fire for
a clean session vs a thrash session vs a lookup-heavy session, and that
--out JSON is what lenses should read.

Run: python3 -m unittest discover -s skills/reflect/scripts/tests -v
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
TOKEN_AUDIT = os.path.join(SCRIPTS_DIR, "token_audit.py")
sys.path.insert(0, SCRIPTS_DIR)

import token_audit  # noqa: E402

FLAG_NAMES = (
    "model-tier-candidates",
    "redundant-reads",
    "recurring-failure-signatures",
    "no-verify-edit-streak",
    "cache-creation-spikes",
)


def fixture(name):
    path = os.path.join(FIXTURES, name)
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    return path


def flag_map(report):
    return {fl["name"]: fl for fl in report["flags"]}


def run_cli(session_path, out_path):
    """Invoke token_audit.py as a real subprocess — the e2e path lenses use."""
    proc = subprocess.run(
        [sys.executable, TOKEN_AUDIT, "claude", session_path, "--out", out_path],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc


class TestE2ECleanEfficientSession(unittest.TestCase):
    """Read → Edit → pytest. High cache-read. No thrash flags."""

    @classmethod
    def setUpClass(cls):
        cls.path = fixture("clean_efficient_session.jsonl")

    def test_cli_out_report_has_no_thrash_flags(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            out = f.name
        try:
            proc = run_cli(self.path, out)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn(out, proc.stdout)
            self.assertNotIn("redundant re-reads (identical window)", proc.stdout)
            with open(out) as fh:
                report = json.load(fh)
            flags = flag_map(report)
            self.assertEqual(set(flags), set(FLAG_NAMES))
            for name in (
                "redundant-reads",
                "recurring-failure-signatures",
                "no-verify-edit-streak",
                "cache-creation-spikes",
                "model-tier-candidates",
            ):
                self.assertEqual(flags[name]["value"], "no", flags[name])
            # Cache-read should dominate a clean session (recommendation: tails,
            # not averages — this fixture is the "healthy" baseline).
            totals = report["totals"]
            self.assertGreater(totals["cache_read"], totals["input"])
            self.assertGreater(totals["cache_read_share"], 0.9)
            # Dedup: multi-block turn (thinking+text+tool_use) counted once.
            self.assertEqual(totals["n_assistant"], 3)
            self.assertEqual(totals["n_errors"], 0)
        finally:
            os.unlink(out)

    def test_api_matches_cli_totals(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            out = f.name
        try:
            with redirect_stdout(io.StringIO()):
                result = token_audit.audit_claude(self.path, out_path=out)
            with open(out) as fh:
                report = json.load(fh)
            self.assertEqual(result["total"], report["totals"]["total"])
            self.assertEqual(result["n_assistant"], report["totals"]["n_assistant"])
            self.assertEqual(result["longest_edit_streak_no_verify"], 1)
        finally:
            os.unlink(out)


class TestE2ETokenThrashSession(unittest.TestCase):
    """Every cost-audit detector should fire — the Cost lens recommendation set."""

    @classmethod
    def setUpClass(cls):
        cls.path = fixture("token_thrash_session.jsonl")

    def test_cli_all_five_flags_yes(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            out = f.name
        try:
            proc = run_cli(self.path, out)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            with open(out) as fh:
                report = json.load(fh)
            flags = flag_map(report)
            for name in FLAG_NAMES:
                self.assertEqual(flags[name]["value"], "yes", f"{name}: {flags[name]}")
                self.assertGreaterEqual(flags[name]["count"], 1)
                self.assertTrue(flags[name]["rationale"])
            # Same-problem thrash recommendations named in cost-audit.md
            self.assertIn("recurring", flags["recurring-failure-signatures"]["rationale"])
            self.assertIn("verification", flags["no-verify-edit-streak"]["rationale"])
            self.assertGreaterEqual(report["totals"]["n_errors"], 3)
            # Stdout is the short summary lenses skim; flag lines present.
            for name in FLAG_NAMES:
                self.assertIn(f"{name}: yes", proc.stdout)
        finally:
            os.unlink(out)

    def test_api_feedback_loop_numbers_match_flags(self):
        with redirect_stdout(io.StringIO()):
            result = token_audit.audit_claude(self.path)
        self.assertGreaterEqual(result["n_recurring_failures"], 1)
        self.assertGreaterEqual(result["longest_edit_streak_no_verify"], 3)
        flags = {fl["name"]: fl for fl in result["flags"]}
        self.assertEqual(flags["no-verify-edit-streak"]["count"],
                         result["longest_edit_streak_no_verify"])


class TestE2ELookupHeavySession(unittest.TestCase):
    """Lookup-only turns → model-tier downgrade candidate with $ backtest."""

    @classmethod
    def setUpClass(cls):
        cls.path = fixture("lookup_heavy_session.jsonl")

    def test_cli_model_tier_flag_and_backtest_rationale(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            out = f.name
        try:
            proc = run_cli(self.path, out)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            with open(out) as fh:
                report = json.load(fh)
            flags = flag_map(report)
            self.assertEqual(flags["model-tier-candidates"]["value"], "yes")
            self.assertGreaterEqual(flags["model-tier-candidates"]["count"], 3)
            rationale = flags["model-tier-candidates"]["rationale"]
            self.assertIn("backtest", rationale)
            self.assertIn("claude-haiku-4-5", rationale)
            self.assertIn("$", rationale)
            # No thrash noise on a pure lookup conversation
            for name in (
                "redundant-reads",
                "recurring-failure-signatures",
                "no-verify-edit-streak",
                "cache-creation-spikes",
            ):
                self.assertEqual(flags[name]["value"], "no", flags[name])
            # Reproducible lower-bound savings from published prices
            # 3 lookup turns × 500 output tokens = 1500; sonnet $15/MTok vs haiku $5/MTok
            actual, cheaper, saved = token_audit.model_tier_savings(1500)
            self.assertAlmostEqual(saved, actual - cheaper)
            self.assertGreater(saved, 0)
        finally:
            os.unlink(out)


class TestE2EFixtureIntegrity(unittest.TestCase):
    """Fixtures stay regenerable and discoverable; no silent empty files."""

    def test_all_sample_fixtures_exist_and_parse(self):
        expected = {
            "clean_efficient_session.jsonl",
            "token_thrash_session.jsonl",
            "lookup_heavy_session.jsonl",
        }
        found = {n for n in os.listdir(FIXTURES) if n.endswith(".jsonl")}
        self.assertEqual(found, expected)
        for name in expected:
            path = fixture(name)
            n = 0
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    json.loads(line)
                    n += 1
            self.assertGreater(n, 5, name)

    def test_generator_script_is_present(self):
        gen = os.path.join(FIXTURES, "generate_sample_conversations.py")
        self.assertTrue(os.path.isfile(gen))


if __name__ == "__main__":
    unittest.main()
