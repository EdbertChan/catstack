#!/usr/bin/env python3
"""Deploy merge collection must not silently cap at a page size (e.g. 100)."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS_DIR)

import collect_dora_events as cde  # noqa: E402


class TestDeployUncapped(unittest.TestCase):
    def test_source_has_no_hardcoded_limit_100(self):
        path = os.path.join(SCRIPTS_DIR, "collect_dora_events.py")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn('"100"', src)
        self.assertNotIn("'100'", src)
        self.assertIn("GH_SEARCH_HARD_CAP = 1000", src)
        self.assertIn("bisect", src.lower())

    def test_git_first_parent_returns_more_than_100(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-b", "main"], cwd=tmp, check=True, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=tmp,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"],
                cwd=tmp,
                check=True,
                capture_output=True,
            )
            n = 150
            for i in range(n):
                path = os.path.join(tmp, "f.txt")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(str(i))
                subprocess.run(["git", "add", "f.txt"], cwd=tmp, check=True, capture_output=True)
                subprocess.run(
                    ["git", "commit", "-m", f"c{i}"],
                    cwd=tmp,
                    check=True,
                    capture_output=True,
                )
            until = datetime.now(timezone.utc) + timedelta(hours=1)
            since = until - timedelta(days=7)
            events = cde.events_from_git_merges(tmp, since=since, until=until)
            self.assertEqual(len(events), n)
            self.assertGreater(len(events), 100)


if __name__ == "__main__":
    unittest.main()
