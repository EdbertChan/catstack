#!/usr/bin/env python3
"""Hit / clean / unchecked tests for check_history_claims, plus the open-stdin hang."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "check_history_claims.py"

CLAIM = "This retry loop has been broken for five months.\n"
SOURCED = "`git log -S retry` dates it: broken for five months.\n"


def _run(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], input=stdin, capture_output=True, text=True, timeout=30
    )


class TestHistoryClaims(unittest.TestCase):
    def test_no_file_with_open_stdin_does_not_hang(self):
        proc = subprocess.Popen(
            [sys.executable, str(SCRIPT)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            code = proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            self.fail("check_history_claims.py blocked on an open stdin with no FILE given")
        out, err = proc.communicate()
        self.assertEqual(code, 0, out + err)
        self.assertIn("UNCHECKED", out)
        self.assertNotIn("OK", out)

    def test_unsourced_claim_in_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "body.md"
            path.write_text(CLAIM, encoding="utf-8")
            result = _run(str(path))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("body.md:1: duration claim", result.stdout)

    def test_sourced_claim_in_file_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "body.md"
            path.write_text(SOURCED, encoding="utf-8")
            result = _run(str(path))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("OK: no unsourced history claims", result.stdout)

    def test_dash_reads_stdin(self):
        result = _run("-", stdin=CLAIM)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("stdin:1: duration claim", result.stdout)

    def test_missing_file_is_unchecked_not_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(str(Path(tmp) / "absent.md"))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("UNCHECKED", result.stderr)
        self.assertNotIn("OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
