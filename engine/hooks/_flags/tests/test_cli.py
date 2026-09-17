#!/usr/bin/env python3
"""The command-line lookup prints one of three words, never a clean `off` for
a file it could not read.

Run: python3 -m unittest discover -s engine/hooks/_flags/tests -v
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
import unittest

FLAGS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, FLAGS_DIR)

import flags  # noqa: E402

KEY = "CATSTACK_REFLECT_ENFORCEMENT"


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(os.path.join(self.repo, ".git"))
        self.environ = {"HOME": os.path.join(self.tmp.name, "home")}
        os.makedirs(self.environ["HOME"])

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        code = flags.main(list(argv), environ=self.environ, stdout=out, stderr=err)
        return code, out.getvalue().strip(), err.getvalue()

    def test_unset_prints_off(self):
        self.assertEqual(self.run_main(KEY, "--cwd", self.repo), (0, "off", ""))

    def test_environment_on_prints_on(self):
        self.environ[KEY] = "1"
        self.assertEqual(self.run_main(KEY, "--cwd", self.repo)[:2], (0, "on"))

    def test_repo_env_file_is_read_from_cwd(self):
        with open(os.path.join(self.repo, ".env"), "w", encoding="utf-8") as handle:
            handle.write(f"{KEY}=yes\n")
        self.assertEqual(self.run_main(KEY, "--cwd", self.repo)[:2], (0, "on"))

    def test_unreadable_file_prints_unchecked_and_names_the_file(self):
        os.makedirs(os.path.join(self.repo, ".env"))
        code, state, err = self.run_main(KEY, "--cwd", self.repo)
        self.assertEqual((code, state), (0, "unchecked"))
        self.assertIn(os.path.join(self.repo, ".env"), err)

    def test_value_prints_the_raw_setting(self):
        self.environ["CATSTACK_CAT_MODE_DEFAULT"] = " Decide "
        self.assertEqual(
            self.run_main("CATSTACK_CAT_MODE_DEFAULT", "--value", "--cwd", self.repo), (0, "decide", "")
        )

    def test_value_unset_prints_empty(self):
        self.assertEqual(self.run_main(KEY, "--value", "--cwd", self.repo), (0, "", ""))

    def test_value_unreadable_prints_unchecked(self):
        os.makedirs(os.path.join(self.repo, ".env"))
        self.assertEqual(self.run_main(KEY, "--value", "--cwd", self.repo)[:2], (0, "unchecked"))

    def test_runs_as_a_script(self):
        env = {**os.environ, **self.environ, KEY: "on"}
        result = subprocess.run(
            [sys.executable, os.path.join(FLAGS_DIR, "flags.py"), KEY, "--cwd", self.repo],
            capture_output=True, text=True, env=env, timeout=20,
        )
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "on"), result.stderr)


if __name__ == "__main__":
    unittest.main()
