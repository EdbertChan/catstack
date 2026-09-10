#!/usr/bin/env python3
"""Positive + negative tests for scripts/ensure_node_toolchain.sh.

scripts/run_all_tests.sh runs suites that shell out to Node
(engine/skills/draft-pr), so a checkout with no node_modules cannot run
them. The negative controls are the point: a missing npm and a failing
`npm ci` must each exit non-zero with a named reason, never let the
suite report a green run over a suite that never ran.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "ensure_node_toolchain.sh"
RUNNER = REPO / "scripts" / "run_all_tests.sh"
BASH = shutil.which("bash") or "/bin/bash"
BASE_PATH = os.environ.get("PATH", "/usr/bin:/bin")


def _fake_repo(tmp: str, *, package_json: bool = True, node_modules: bool = False) -> Path:
    root = Path(tmp) / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "ensure_node_toolchain.sh").write_text(
        SCRIPT.read_text(encoding="utf-8"), encoding="utf-8"
    )
    if package_json:
        (root / "package.json").write_text('{"name":"x"}\n', encoding="utf-8")
    if node_modules:
        (root / "node_modules").mkdir()
    return root


def _path_with_npm(tmp: str, body: str) -> str:
    bindir = Path(tmp) / "bin"
    bindir.mkdir()
    npm = bindir / "npm"
    npm.write_text(body, encoding="utf-8")
    npm.chmod(npm.stat().st_mode | stat.S_IXUSR)
    return f"{bindir}:{BASE_PATH}"


def _path_without_npm(tmp: str) -> str:
    """Everything the script needs from PATH except npm: only dirname is external."""
    bindir = Path(tmp) / "nonpm-bin"
    bindir.mkdir()
    (bindir / "dirname").symlink_to(shutil.which("dirname") or "/usr/bin/dirname")
    return str(bindir)


def _run(root: Path, path: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PATH=path)
    return subprocess.run(
        [BASH, str(root / "scripts" / "ensure_node_toolchain.sh")],
        capture_output=True, text=True, timeout=300, env=env,
    )


class TestCannotRunIsNotAPass(unittest.TestCase):
    def test_missing_npm_fails_with_a_named_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _fake_repo(tmp)
            result = _run(root, _path_without_npm(tmp))
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("npm not found", result.stderr)

    def test_failing_npm_ci_is_reported_not_swallowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _fake_repo(tmp)
            path = _path_with_npm(tmp, "#!/bin/bash\necho 'registry unreachable' >&2\nexit 1\n")
            result = _run(root, path)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("npm ci failed", result.stderr)
            self.assertIn("registry unreachable", result.stderr)


class TestInstalls(unittest.TestCase):
    def test_missing_node_modules_triggers_npm_ci(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _fake_repo(tmp)
            path = _path_with_npm(tmp, f"#!/bin/bash\nmkdir -p '{root}/node_modules'\necho \"$@\" > '{root}/npm-args'\n")
            result = _run(root, path)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((root / "npm-args").read_text(encoding="utf-8").strip(), "ci")
            self.assertTrue((root / "node_modules").is_dir())

    def test_existing_node_modules_installs_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _fake_repo(tmp, node_modules=True)
            result = _run(root, _path_without_npm(tmp))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("already installed", result.stdout)

    def test_repo_without_package_json_needs_no_toolchain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _fake_repo(tmp, package_json=False)
            result = _run(root, _path_without_npm(tmp))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("no package.json", result.stdout)


class TestWiredIntoTheRunner(unittest.TestCase):
    def test_run_all_tests_bootstraps_before_discovering_suites(self):
        text = RUNNER.read_text(encoding="utf-8")
        self.assertIn("bash scripts/ensure_node_toolchain.sh || status=1", text)
        self.assertLess(
            text.index("ensure_node_toolchain.sh"), text.index("unittest discover")
        )

    def test_this_checkout_has_the_node_toolchain(self):
        result = subprocess.run(
            [BASH, str(SCRIPT)], capture_output=True, text=True, timeout=300
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
