#!/usr/bin/env python3
"""The sibling-path import has to resolve where hooks actually run.

install.sh links each hook directory separately into the harness hooks folder,
so a hook reaches this module through its own parent directory. That only
works because the path is built with abspath, which leaves the symlink in
place; realpath would jump into the checkout and find nothing beside it in a
partial install. This test builds that layout for real rather than trusting
the shape.

Three harnesses, not one. scope-lock and wrong-check-reflect are linked into
~/.cursor/hooks and ~/.codex/hooks as well, and both now import this module at
load time. A `_flags` link that reaches only Claude would leave those two dead
on the other two harnesses -- and dead means the flag can never turn them on
there, which reads exactly like "the user did not opt in".

Run: python3 -m unittest discover -s engine/hooks/_flags/tests -v
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

FLAGS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS_DIR = os.path.dirname(FLAGS_DIR)
REPO_DIR = os.path.dirname(os.path.dirname(HOOKS_DIR))
INSTALL_SH = os.path.join(REPO_DIR, "install.sh")

CONSUMER = (
    "import os, sys\n"
    "sys.path.insert(0, os.path.join("
    "os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '_flags'))\n"
    "from flags import enforcement_gate, REFLECT_ENFORCEMENT\n"
    "print(enforcement_gate('consumer', None))\n"
)

HARNESS_DIRS = (
    ("claude", os.path.join(".claude", "hooks")),
    ("cursor", os.path.join(".cursor", "hooks")),
    ("codex", os.path.join(".codex", "hooks")),
)


class InstalledLayout(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="flags-install-")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.installed_hooks = os.path.join(self.home, ".claude", "hooks")
        os.makedirs(self.installed_hooks)

    def _link(self, name, src):
        target = os.path.join(self.installed_hooks, name)
        os.symlink(src, target)
        return target

    def _run_consumer(self, consumer_dir, env=None):
        script = os.path.join(consumer_dir, "detect.py")
        with open(script, "w", encoding="utf-8") as handle:
            handle.write(CONSUMER)
        environ = dict(os.environ)
        environ["HOME"] = self.home
        environ.pop("CATSTACK_REFLECT_ENFORCEMENT", None)
        environ.pop("CATSTACK_ENV_FILE", None)
        environ.update(env or {})
        return subprocess.run(
            [sys.executable, os.path.join(self.installed_hooks, "consumer", "detect.py")],
            capture_output=True,
            text=True,
            env=environ,
        )

    def _consumer(self):
        real = tempfile.mkdtemp(prefix="flags-consumer-")
        self.addCleanup(shutil.rmtree, real, ignore_errors=True)
        self._link("consumer", real)
        return real

    def test_consumer_imports_flags_through_symlinked_siblings(self):
        self._link("_flags", FLAGS_DIR)
        result = self._run_consumer(self._consumer())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "False")

    def test_the_flag_reaches_the_consumer_in_the_installed_layout(self):
        self._link("_flags", FLAGS_DIR)
        result = self._run_consumer(
            self._consumer(), env={"CATSTACK_REFLECT_ENFORCEMENT": "1"}
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "True")

    def test_missing_flags_link_fails_loudly_instead_of_passing_clean(self):
        result = self._run_consumer(self._consumer())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ModuleNotFoundError", result.stderr)


class InstallerWiring(unittest.TestCase):
    """A hook that imports _flags is dead wherever _flags was not linked.

    The link is what makes the flag reachable, so it is asserted per harness
    rather than once -- a single `link_item "_flags"` anywhere in the file
    would satisfy a looser check while two harnesses stayed broken.
    """

    def setUp(self):
        with open(INSTALL_SH, encoding="utf-8") as handle:
            self.body = handle.read()

    def test_install_sh_links_flags_into_every_harness_hooks_dir(self):
        for harness, relative in HARNESS_DIRS:
            with self.subTest(harness=harness):
                expected = '"$HOME/{}/_flags"'.format(relative.replace(os.sep, "/"))
                self.assertIn(expected, self.body)

    def test_every_hook_importing_flags_is_linked_where_it_is_installed(self):
        """Names the gap rather than trusting the list above to stay current."""
        importers = set()
        for entry in sorted(os.listdir(HOOKS_DIR)):
            hook_dir = os.path.join(HOOKS_DIR, entry)
            if not os.path.isdir(hook_dir) or entry.startswith("_"):
                continue
            for name in os.listdir(hook_dir):
                if not name.endswith(".py"):
                    continue
                with open(os.path.join(hook_dir, name), encoding="utf-8") as handle:
                    if "from flags import" in handle.read():
                        importers.add(entry)
                        break
        self.assertTrue(importers, "no hook imports flags; this test is now vacuous")
        checked = 0
        for hook in sorted(importers):
            for harness, relative in HARNESS_DIRS:
                folder = relative.replace(os.sep, "/")
                installed = re.search(
                    r'link_item "{}" "\$REPO_DIR/engine/hooks/{}" "\$HOME/{}/{}"'.format(
                        re.escape(hook), re.escape(hook), re.escape(folder), re.escape(hook)
                    ),
                    self.body,
                )
                if not installed:
                    continue
                checked += 1
                with self.subTest(hook=hook, harness=harness):
                    self.assertIn(
                        '"$HOME/{}/_flags"'.format(folder),
                        self.body,
                        f"{hook} is installed into {folder} but _flags is not",
                    )
        self.assertTrue(
            checked,
            "matched no link_item line for any flags-importing hook -- the regex "
            "no longer matches install.sh, so this test checked nothing",
        )


if __name__ == "__main__":
    unittest.main()
