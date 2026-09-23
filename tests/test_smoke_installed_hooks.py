#!/usr/bin/env python3
"""The installed-hook smoke sweep: one outcome per script, and never a clean
pass when it could not look.

Run: python3 -m unittest tests.test_smoke_installed_hooks -v
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "install"))

import smoke_installed_hooks as smoke  # noqa: E402

GOOD = "import json, os\n\n\ndef main():\n    print('{}')\n\n\nif __name__ == '__main__':\n    main()\n"
BROKEN = "import os, sys\nsys.path.insert(0, os.path.join(os.path.dirname(__file__), 'nowhere'))\nfrom finding import Finding\n"
HANGS = "import time\ntime.sleep(30)\n"
RAISES_AT_IMPORT = "raise RuntimeError('boom')\n"
SKIPPED = "from finding import Finding\n"


class SmokeSweepTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = self.tmp.name

    def write(self, harness, hook, name, body):
        path = os.path.join(self.home, harness, "hooks", hook, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
        return path

    def run_main(self, *argv):
        out = io.StringIO()
        code = smoke.main(["--home", self.home, *argv], stdout=out)
        return code, out.getvalue()

    def test_a_loadable_hook_passes(self):
        self.write(".claude", "good-hook", "claude_stop_check.py", GOOD)
        code, text = self.run_main()
        self.assertEqual(code, 0, text)
        self.assertIn("checked=1 unreadable=0 import-fail=0", text)

    def test_a_missing_shared_module_fails_and_names_the_script(self):
        self.write(".claude", "diu-stop", "claude_stop_check.py", BROKEN)
        code, text = self.run_main()
        self.assertEqual(code, 1, text)
        self.assertIn(".claude/hooks/diu-stop/claude_stop_check.py", text)
        self.assertIn("No module named 'finding'", text)
        self.assertIn("import-fail=1", text)

    def test_every_harness_is_swept(self):
        for harness in (".claude", ".cursor", ".codex"):
            self.write(harness, "diu-stop", "claude_stop_check.py", BROKEN)
        code, text = self.run_main()
        self.assertEqual(code, 1, text)
        self.assertIn("import-fail=3", text)
        for harness in (".claude", ".cursor", ".codex"):
            self.assertIn(f"{harness}/hooks/diu-stop/claude_stop_check.py", text)

    def test_main_guard_is_not_executed(self):
        marker = os.path.join(self.home, "ran-main")
        body = f"import pathlib\n\n\nif __name__ == '__main__':\n    pathlib.Path({marker!r}).write_text('x')\n"
        self.write(".claude", "side-effect", "claude_stop_check.py", body)
        code, text = self.run_main()
        self.assertEqual(code, 0, text)
        self.assertFalse(os.path.exists(marker), "the smoke sweep must not run a hook's main()")

    def test_a_hook_that_works_at_import_time_is_slow_not_failed(self):
        self.write(".claude", "busy-hook", "claude_stop_check.py", HANGS)
        code, text = self.run_main("--timeout", "1")
        self.assertEqual(code, 0, text)
        self.assertIn("slow=1", text)
        self.assertIn("imports resolved", text)

    def test_a_non_import_error_is_not_an_install_defect(self):
        self.write(".claude", "angry-hook", "claude_stop_check.py", RAISES_AT_IMPORT)
        code, text = self.run_main()
        self.assertEqual(code, 0, text)
        self.assertIn("import-fail=0", text)

    def test_shared_dirs_installers_and_tests_are_not_entry_points(self):
        self.write(".claude", "_sdk", "runtime.py", SKIPPED)
        self.write(".claude", "diu-stop", "install_claude_hook.py", SKIPPED)
        self.write(".claude", "diu-stop", "test_hooks.py", SKIPPED)
        self.write(".claude", "diu-stop", "detect.py", SKIPPED)
        self.write(".claude", "diu-stop", "state.py", SKIPPED)
        code, text = self.run_main()
        self.assertEqual(code, 2, text)
        self.assertIn("checked=0", text)

    def test_a_hook_that_cannot_be_opened_fails_and_names_its_target(self):
        """stat() succeeds on a mode-000 file, so existence tests pass while
        every real hook run dies on open()."""
        path = self.write(".claude", "locked-hook", "claude_stop_check.py", GOOD)
        os.chmod(path, 0o000)
        self.addCleanup(os.chmod, path, 0o644)
        self.assertTrue(os.path.exists(path), "stat() still succeeds; that is the trap")
        code, text = self.run_main()
        self.assertEqual(code, 1, text)
        self.assertIn("unreadable=1", text)
        self.assertIn(".claude/hooks/locked-hook/claude_stop_check.py", text)
        self.assertIn(os.path.realpath(path), text)
        self.assertIn("PermissionError", text)
        self.assertIn("cannot be opened by the interpreter", text)

    def test_a_dangling_link_is_unreadable_not_ok(self):
        target = os.path.join(self.home, "gone", "claude_stop_check.py")
        link = os.path.join(self.home, ".claude", "hooks", "dead-link", "claude_stop_check.py")
        os.makedirs(os.path.dirname(link), exist_ok=True)
        os.symlink(target, link)
        code, text = self.run_main()
        self.assertEqual(code, 1, text)
        self.assertIn("unreadable=1", text)
        self.assertIn("FileNotFoundError", text)

    def test_a_target_under_documents_names_the_macos_cause(self):
        """The checkout lives under ~/Documents, where a TCC denial -- not a
        broken link -- is the likely reason open() fails."""
        target = os.path.join(os.path.expanduser("~/Documents"), "catstack-smoke-absent.py")
        self.assertFalse(os.path.exists(target), "the probe must not clobber a real file")
        link = os.path.join(self.home, ".claude", "hooks", "docs-hook", "claude_stop_check.py")
        os.makedirs(os.path.dirname(link), exist_ok=True)
        os.symlink(target, link)
        code, text = self.run_main()
        self.assertEqual(code, 1, text)
        self.assertIn("Full Disk Access", text)

    def test_a_symlinked_documents_still_names_the_macos_cause(self):
        """Documents is itself a symlink whenever it lives on iCloud Drive or an
        external volume. The reported target is resolved, so it never starts
        with the unresolved ~/Documents -- the hint has to resolve both sides."""
        real_docs = os.path.join(self.home, "elsewhere", "Documents")
        os.makedirs(real_docs, exist_ok=True)
        os.symlink(real_docs, os.path.join(self.home, "Documents"))
        home_env = mock.patch.dict(os.environ, {"HOME": self.home})
        home_env.start()
        self.addCleanup(home_env.stop)
        target = os.path.join(self.home, "Documents", "catstack", "claude_stop_check.py")
        link = os.path.join(self.home, ".claude", "hooks", "docs-hook", "claude_stop_check.py")
        os.makedirs(os.path.dirname(link), exist_ok=True)
        os.symlink(target, link)
        code, text = self.run_main()
        self.assertEqual(code, 1, text)
        self.assertIn("unreadable=1", text)
        self.assertIn("Full Disk Access", text)

    def test_readability_is_checked_before_imports(self):
        """An unreadable script reports unreadable, never import-fail: the open()
        probe runs first, so the more specific cause is the one reported."""
        path = self.write(".claude", "locked-broken", "claude_stop_check.py", BROKEN)
        os.chmod(path, 0o000)
        self.addCleanup(os.chmod, path, 0o644)
        code, text = self.run_main()
        self.assertEqual(code, 1, text)
        self.assertIn("unreadable=1 import-fail=0", text)

    def test_no_hooks_at_all_is_unchecked_not_clean(self):
        code, text = self.run_main()
        self.assertEqual(code, 2, text)
        self.assertIn("UNCHECKED", text)
        self.assertIn("nothing was verified", text)


if __name__ == "__main__":
    unittest.main()
