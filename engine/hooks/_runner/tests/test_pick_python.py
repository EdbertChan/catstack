from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER_DIR)

import run  # noqa: E402

OLD_PYTHON = "/usr/bin/python3"


def old_python_available() -> bool:
    if not os.path.isfile(OLD_PYTHON):
        return False
    probe = subprocess.run([OLD_PYTHON, "-c", "import sys; print(sys.version_info[:2] < (3, 11))"], capture_output=True, text=True)
    return probe.stdout.strip() == "True"


class PickPython(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def fake(self, name: str) -> str:
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\n")
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        return path

    def test_new_enough_runner_keeps_its_own_python(self) -> None:
        self.assertEqual(run._pick_python((3, 12), "/x/python3", [self.tmp.name], {}), "/x/python3")

    def test_old_runner_finds_a_versioned_python_in_a_search_dir(self) -> None:
        self.fake("python3.10")
        found = self.fake("python3.13")
        self.fake("python3.12")
        self.assertEqual(run._pick_python((3, 9), "/usr/bin/python3", [self.tmp.name], {}), found)

    def test_override_wins_when_it_exists(self) -> None:
        self.fake("python3.13")
        chosen = self.fake("mine")
        env = {"CATSTACK_HOOK_PYTHON": chosen}
        self.assertEqual(run._pick_python((3, 9), "/usr/bin/python3", [self.tmp.name], env), chosen)

    def test_old_runner_with_nothing_new_enough_returns_none(self) -> None:
        self.fake("python3.10")
        self.assertIsNone(run._pick_python((3, 9), "/usr/bin/python3", [self.tmp.name], {}))


@unittest.skipUnless(old_python_available(), f"needs a Python older than 3.11 at {OLD_PYTHON}")
class OldPythonRunnerEndToEnd(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        hooks_root = os.path.join(self.tmp.name, "home", ".claude", "hooks")
        self.runner_dir = os.path.join(hooks_root, "_runner")
        fixture_dir = os.path.join(hooks_root, "fixture")
        os.makedirs(self.runner_dir)
        os.makedirs(fixture_dir)
        for name in ("run.py", "outcome.py"):
            shutil.copy2(os.path.join(RUNNER_DIR, name), os.path.join(self.runner_dir, name))
        with open(os.path.join(fixture_dir, "needs_new.py"), "w", encoding="utf-8") as handle:
            handle.write("import json, sys, tomllib\nprint(json.dumps({'version': list(sys.version_info[:2])}))\n")

    def run_under_old_python(self, env: dict[str, str]) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [OLD_PYTHON, os.path.join(self.runner_dir, "run.py"), "--timeout", "20", "fixture/needs_new.py"],
            input=json.dumps({"hook_event_name": "Stop", "session_id": "s1"}).encode(),
            capture_output=True,
            env=env,
            timeout=30,
        )

    def test_hook_runs_on_a_new_python_when_the_runner_starts_on_an_old_one(self) -> None:
        env = {**os.environ, "CATSTACK_HOOK_METRICS_DIR": os.path.join(self.tmp.name, "metrics"), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}
        env.pop("CATSTACK_HOOK_PYTHON", None)
        result = self.run_under_old_python(env)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertGreaterEqual(tuple(json.loads(result.stdout)["version"]), (3, 11))

    def test_no_new_python_says_so_instead_of_an_import_traceback(self) -> None:
        env = {**os.environ, "CATSTACK_HOOK_METRICS_DIR": os.path.join(self.tmp.name, "metrics"), "PATH": "/usr/bin:/bin",
               "CATSTACK_HOOK_PYTHON_DIRS": os.path.join(self.tmp.name, "empty")}
        env.pop("CATSTACK_HOOK_PYTHON", None)
        result = self.run_under_old_python(env)
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"needs Python 3.11 or newer", result.stderr)
        self.assertNotIn(b"Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
