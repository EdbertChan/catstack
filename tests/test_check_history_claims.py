#!/usr/bin/env python3
"""check_history_claims.py never waits on stdin unasked, and a check that could
not read its input exits 2 (unchecked), never 0 (clean)."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GATE = REPO / "scripts" / "check_history_claims.py"


def run(*args: str, stdin_text: str | None = None, hold_stdin_open: bool = False) -> subprocess.CompletedProcess:
    proc = subprocess.Popen(
        [sys.executable, str(GATE), *args],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=REPO,
    )
    try:
        if hold_stdin_open:
            proc.wait(timeout=30)
            out, err = proc.stdout.read(), proc.stderr.read()
        else:
            out, err = proc.communicate(stdin_text or "", timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            stream.close()
    return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)


class TestNoArgRun(unittest.TestCase):
    def test_no_args_does_not_wait_on_an_open_stdin(self):
        result = run(hold_stdin_open=True)
        self.assertIn(result.returncode, (0, 1, 2), result.stderr)
        self.assertNotIn("stdin:", result.stdout)

    def test_base_scans_commit_messages(self):
        result = run("--base", "HEAD~1")
        self.assertIn(result.returncode, (0, 1), result.stderr)
        self.assertNotIn("UNCHECKED", result.stderr)

    def test_unresolvable_base_is_unchecked_not_clean(self):
        result = run("--base", "no-such-ref-for-history-claims")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("UNCHECKED: cannot resolve merge-base", result.stderr)


class TestTargets(unittest.TestCase):
    def test_dash_reads_stdin(self):
        result = run("-", stdin_text="This hook ran for five months before anyone noticed.\n")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("stdin:1: duration claim", result.stdout)

    def test_missing_file_is_unchecked_not_clean(self):
        result = run(str(REPO / "no-such-file-for-history-claims.md"))
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("is not a readable file", result.stderr)

    def test_file_with_a_claim_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "body.md"
            path.write_text("Three review passes found this bug.\n", encoding="utf-8")
            result = run(str(path))
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("body.md:1: count claim", result.stdout)


if __name__ == "__main__":
    unittest.main()
