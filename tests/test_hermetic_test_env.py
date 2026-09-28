#!/usr/bin/env python3
"""The test runner hides this machine from every test.

A test that reads the machine it runs on passes or fails by whose machine it
is: `CATSTACK_UNVERIFIED_TAG_BEHAVIOR=do_not_emit` in one person's
~/.catstack.env failed seven ledger tests that pass in CI. The runner sources
scripts/test/hermetic_env.sh before any suite runs; these tests start that
script from a deliberately polluted environment and check nothing gets
through: no inherited CATSTACK_* or GIT_* variable, a throwaway HOME and git
config, and a flag reader that will not open the real ~/.catstack.env or the
checkout's own .env.

Run: python3 -m unittest tests/test_hermetic_test_env.py -v
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETUP = os.path.join(REPO, "scripts", "test", "hermetic_env.sh")
RUNNER = os.path.join(REPO, "scripts", "test", "run_all_tests.sh")

PROBE = r"""
import json, os, sys
sys.path.insert(0, os.path.join(sys.argv[1], "engine", "hooks", "_flags"))
import flags
print(json.dumps({
    "env": dict(os.environ),
    "candidates": flags.env_file_candidates(dict(os.environ), sys.argv[1]),
}))
"""


class HermeticEnvTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.real_home = os.path.join(tmp.name, "real-home")
        os.makedirs(self.real_home)
        with open(os.path.join(self.real_home, ".catstack.env"), "w", encoding="utf-8") as handle:
            handle.write("CATSTACK_UNVERIFIED_TAG_BEHAVIOR=do_not_emit\n")
        polluted = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": self.real_home,
            "CATSTACK_UNVERIFIED_TAG_BEHAVIOR": "do_not_emit",
            "CATSTACK_ENV_FILE": os.path.join(self.real_home, ".catstack.env"),
            "GIT_DIR": "/nowhere/.git",
            "XDG_CONFIG_HOME": os.path.join(self.real_home, ".config"),
        }
        result = subprocess.run(
            ["bash", "-c", 'source "$1" && python3 -c "$2" "$3"', "_", SETUP, PROBE, REPO],
            env=polluted, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.seen = json.loads(result.stdout)

    def test_no_inherited_catstack_or_git_variable_survives(self) -> None:
        env = self.seen["env"]
        self.assertNotIn("CATSTACK_UNVERIFIED_TAG_BEHAVIOR", env)
        self.assertNotIn("CATSTACK_ENV_FILE", env)
        self.assertNotIn("GIT_DIR", env)
        self.assertNotIn("XDG_CONFIG_HOME", env)

    def test_home_and_git_config_are_throwaway(self) -> None:
        env = self.seen["env"]
        self.assertNotEqual(env["HOME"], self.real_home)
        self.assertTrue(env["HOME"].startswith(tempfile.gettempdir()) or "catstack-test-home" in env["HOME"])
        self.assertTrue(env["GIT_CONFIG_GLOBAL"].startswith(env["HOME"]))
        self.assertEqual(env.get("GIT_CONFIG_NOSYSTEM"), "1")

    def test_flag_reader_skips_the_real_settings_files(self) -> None:
        candidates = [os.path.realpath(path) for path in self.seen["candidates"]]
        self.assertNotIn(os.path.realpath(os.path.join(self.real_home, ".catstack.env")), candidates)
        self.assertNotIn(os.path.realpath(os.path.join(REPO, ".env")), candidates)

    def test_the_runner_sources_the_setup_before_any_suite(self) -> None:
        with open(RUNNER, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn('source "$REPO_DIR/scripts/test/hermetic_env.sh"', text)
        self.assertLess(text.index("hermetic_env.sh"), text.index("unittest discover"))


if __name__ == "__main__":
    unittest.main()
