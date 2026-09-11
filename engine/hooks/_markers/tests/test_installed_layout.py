#!/usr/bin/env python3
"""The sibling-path import has to resolve where hooks actually run.

install.sh links each hook directory separately into $HOME/.claude/hooks/, so
a hook reaches this module through its own parent directory. That only works
because the path is built with abspath, which leaves the symlink in place;
realpath would jump into the checkout and find nothing beside it in a partial
install. This test builds that layout for real rather than trusting the shape.

Run: python3 -m unittest discover -s engine/hooks/_markers/tests -v
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

MARKERS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS_DIR = os.path.dirname(MARKERS_DIR)

IMPORT_LINE = (
    "import os, sys\n"
    "sys.path.insert(0, os.path.join("
    "os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '_markers'))\n"
    "import markers\n"
    "print(len(markers.well_formed_tags("
    "'{{CAT-UNVERIFIED: x -- cannot verify: offline}}')))\n"
)


class InstalledLayout(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="markers-install-")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.installed_hooks = os.path.join(self.home, ".claude", "hooks")
        os.makedirs(self.installed_hooks)

    def _link(self, name, src):
        target = os.path.join(self.installed_hooks, name)
        os.symlink(src, target)
        return target

    def _run_consumer(self, consumer_dir):
        script = os.path.join(consumer_dir, "detect.py")
        with open(script, "w", encoding="utf-8") as handle:
            handle.write(IMPORT_LINE)
        return subprocess.run(
            [sys.executable, os.path.join(self.installed_hooks, "consumer", "detect.py")],
            capture_output=True,
            text=True,
        )

    def test_consumer_imports_markers_through_symlinked_siblings(self):
        self._link("_markers", MARKERS_DIR)
        real_consumer = tempfile.mkdtemp(prefix="markers-consumer-")
        self.addCleanup(shutil.rmtree, real_consumer, ignore_errors=True)
        self._link("consumer", real_consumer)

        result = self._run_consumer(real_consumer)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "1")

    def test_missing_markers_link_fails_loudly_instead_of_passing_clean(self):
        real_consumer = tempfile.mkdtemp(prefix="markers-consumer-")
        self.addCleanup(shutil.rmtree, real_consumer, ignore_errors=True)
        self._link("consumer", real_consumer)

        result = self._run_consumer(real_consumer)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ModuleNotFoundError", result.stderr)


class InstallerWiring(unittest.TestCase):
    def test_install_sh_links_the_markers_module(self):
        install_sh = os.path.join(os.path.dirname(os.path.dirname(HOOKS_DIR)), "install.sh")
        with open(install_sh, encoding="utf-8") as handle:
            body = handle.read()
        self.assertIn('link_item "_markers"', body)
        self.assertIn('"$HOME/.claude/hooks/_markers"', body)


if __name__ == "__main__":
    unittest.main()
