#!/usr/bin/env python3
"""scripts/check_install_effective.py verifies a real installation.

Its subject is $HOME. install.sh's own suite runs against a throwaway HOME,
where nothing is installed and no harness is authenticated, so the checker
must report a skip there instead of manufacturing drift and failing the
installer with exit 4.

Run: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import importlib.util
import os
import pwd
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO_ROOT, "scripts", "check_install_effective.py")


def load_with_home(home):
    """Import a fresh copy of the checker bound to ``home``.

    The module resolves HOME at import time, so a test that wants a different
    HOME needs its own module instance rather than a mutated global.
    """
    previous = os.environ.get("HOME")
    os.environ["HOME"] = str(home)
    try:
        spec = importlib.util.spec_from_file_location("check_install_effective_under_test", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if previous is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = previous


class TestSandboxHomeIsSkippedNotFailed(unittest.TestCase):
    def test_a_throwaway_home_is_named_as_a_sandbox(self):
        with tempfile.TemporaryDirectory() as home:
            module = load_with_home(home)
            reason = module.sandbox_reason()
            self.assertIsNotNone(reason)
            self.assertIn(home, reason)

    def test_the_users_own_home_is_checked_for_real(self):
        real_home = pwd.getpwuid(os.getuid()).pw_dir
        module = load_with_home(real_home)
        self.assertIsNone(module.sandbox_reason())

    def test_script_exits_zero_and_prints_skip_for_a_sandbox_home(self):
        with tempfile.TemporaryDirectory() as home:
            result = subprocess.run(
                [sys.executable, SCRIPT],
                env={**os.environ, "HOME": home},
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("skip:", result.stdout)
            self.assertNotIn("Installation is not in effect", result.stdout)


class TestCanaryCannotManufactureDrift(unittest.TestCase):
    def test_a_missing_claude_cli_is_unverifiable_not_drift(self):
        with tempfile.TemporaryDirectory() as home:
            module = load_with_home(home)
            claude_dir = Path(home) / ".claude"
            claude_dir.mkdir()
            source = Path(home) / "CLAUDE.md"
            source.write_text("rules", encoding="utf-8")
            (claude_dir / "CLAUDE.md").symlink_to(source)
            previous_path = os.environ.get("PATH", "")
            os.environ["PATH"] = str(Path(home) / "no-binaries-here")
            try:
                drift, unverifiable = module.check_canary()
            finally:
                os.environ["PATH"] = previous_path
        self.assertEqual(drift, [])
        self.assertEqual(len(unverifiable), 1)
        self.assertIn("canary could not run", unverifiable[0])

    def test_an_unlinked_claude_md_leaves_the_canary_silent(self):
        with tempfile.TemporaryDirectory() as home:
            module = load_with_home(home)
            self.assertEqual(module.check_canary(), ([], []))


if __name__ == "__main__":
    unittest.main()
