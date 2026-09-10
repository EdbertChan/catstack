#!/usr/bin/env python3
"""Tests for the Node-toolchain gate in scripts/run_all_tests.sh.

node_modules/ is gitignored, so a fresh clone or a git worktree starts without
it and engine/skills/draft-pr's suites die on ERR_MODULE_NOT_FOUND. This
script is the whole documented test command (CONTRIBUTING.md), so it owns the
toolchain: install what is missing, or refuse with the package names. Three
outcomes, never two -- installed, installable, or a named refusal. Silently
running the suites on a half-present node_modules is the failure this gate
exists to make impossible.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "run_all_tests.sh"

PASSING_SUITE = """import unittest


class Trivial(unittest.TestCase):
    def test_true(self):
        self.assertTrue(True)
"""

NPM_STUB_THAT_INSTALLS_NOTHING = "#!/bin/bash\nexit 0\n"

TOOLS_THE_SCRIPT_SHELLS_OUT_TO = ("python3", "find", "sed", "sort", "dirname", "bash")


def _npm_free_bin(tmp: Path) -> Path:
    """A PATH directory holding every tool the script needs and no npm.

    npm ships at /usr/bin/npm on this class of machine, so trimming PATH down
    to the system directories does not remove it; the directory has to be
    built from resolved tool paths instead.
    """
    bin_dir = tmp / "npm-free-bin"
    bin_dir.mkdir()
    for tool in TOOLS_THE_SCRIPT_SHELLS_OUT_TO:
        resolved = shutil.which(tool)
        if resolved is None:
            raise unittest.SkipTest(f"{tool} is not on PATH, cannot build a test PATH")
        (bin_dir / tool).symlink_to(resolved)
    return bin_dir


def _fake_repo(tmp: Path, *, package: dict | None, installed: list[str]) -> Path:
    (tmp / "scripts").mkdir(parents=True)
    shutil.copy2(SCRIPT, tmp / "scripts" / "run_all_tests.sh")
    (tmp / "tests").mkdir()
    (tmp / "tests" / "test_trivial.py").write_text(PASSING_SUITE, encoding="utf-8")
    if package is not None:
        (tmp / "package.json").write_text(json.dumps(package), encoding="utf-8")
    for name in installed:
        (tmp / "node_modules" / Path(*name.split("/"))).mkdir(parents=True)
    return tmp


def _run(repo: Path, path_env: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PATH=path_env)
    return subprocess.run(
        ["bash", str(repo / "scripts" / "run_all_tests.sh")],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )


class TestNodeDependencyGate(unittest.TestCase):
    maxDiff = None

    def test_missing_package_with_no_npm_is_a_named_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _fake_repo(
                root / "repo",
                package={"devDependencies": {"@scope/absent-pkg": "^1.0.0"}},
                installed=[],
            )
            result = _run(repo, str(_npm_free_bin(root)))
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("@scope/absent-pkg", result.stderr)
        self.assertIn("npm is not on PATH", result.stderr)
        self.assertNotIn("=== ./tests ===", result.stdout)

    def test_npm_that_installs_nothing_fails_instead_of_running_the_suites(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            npm = bin_dir / "npm"
            npm.write_text(NPM_STUB_THAT_INSTALLS_NOTHING, encoding="utf-8")
            npm.chmod(0o755)
            repo = _fake_repo(
                root / "repo",
                package={"devDependencies": {"@scope/absent-pkg": "^1.0.0"}},
                installed=[],
            )
            result = _run(repo, f"{bin_dir}:{_npm_free_bin(root)}")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("still absent", result.stderr)
        self.assertIn("@scope/absent-pkg", result.stderr)
        self.assertNotIn("=== ./tests ===", result.stdout)

    def test_installed_packages_run_the_suites_without_touching_npm(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _fake_repo(
                root / "repo",
                package={"devDependencies": {"@scope/absent-pkg": "^1.0.0"}},
                installed=["@scope/absent-pkg"],
            )
            result = _run(repo, str(_npm_free_bin(root)))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("=== ./tests ===", result.stdout)
        self.assertNotIn("installing Node dependencies", result.stdout)

    def test_repo_without_package_json_is_unaffected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _fake_repo(root / "repo", package=None, installed=[])
            result = _run(repo, str(_npm_free_bin(root)))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("=== ./tests ===", result.stdout)


class TestRealRepoToolchain(unittest.TestCase):
    def test_every_declared_node_package_is_present_in_this_checkout(self):
        package = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))
        names = list(package.get("dependencies") or {})
        names += list(package.get("devDependencies") or {})
        self.assertTrue(names, "package.json declares no Node packages")
        missing = [
            name
            for name in names
            if not (REPO_ROOT / "node_modules" / Path(*name.split("/"))).is_dir()
        ]
        self.assertEqual(missing, [], f"run 'npm ci' in {REPO_ROOT}")


if __name__ == "__main__":
    unittest.main()
