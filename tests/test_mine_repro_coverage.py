#!/usr/bin/env python3
"""Tests for scripts/check_mine_repro_coverage.py."""
from __future__ import annotations

import os
import subprocess
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "check_mine_repro_coverage.py")


class TestMineReproCoverage(unittest.TestCase):
    def test_passes_on_current_repo(self):
        result = subprocess.run(
            ["python3", SCRIPT],
            capture_output=True,
            text=True,
            cwd=REPO,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
