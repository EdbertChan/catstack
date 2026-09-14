#!/usr/bin/env python3
import os
import subprocess
import sys
import unittest


SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestHelpFlags(unittest.TestCase):
    def test_token_audit_help(self):
        proc = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS_DIR, "token_audit.py"), "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Usage", proc.stdout)

    def test_top_sessions_help(self):
        proc = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS_DIR, "top_sessions.py"), "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Usage", proc.stdout)


if __name__ == "__main__":
    unittest.main()
