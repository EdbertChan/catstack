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
# run_all_tests.sh shells out to this sibling before discovering suites, so a
# fake repo that omits it tests a script that cannot run.
TOOLCHAIN_SCRIPT = REPO_ROOT / "scripts" / "ensure_node_toolchain.sh"

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
    shutil.copy2(TOOLCHAIN_SCRIPT, tmp / "scripts" / "ensure_node_toolchain.sh")
    (tmp / "tests").mkdir()
    (tmp / "tests" / "test_trivial.py").write_text(PASSING_SUITE, encoding="utf-8")
    if package is not None:
        (tmp / "package.json").write_text(json.dumps(package), encoding="utf-8")
    for name in installed:
        (tmp / "node_modules" / Path(*name.split("/"))).mkdir(parents=True)
    return tmp


def absent_declared_packages(root: Path) -> list[str] | None:
    """Declared packages with no directory under root/node_modules.

    Three outcomes, never two. [] means every declared package is installed.
    A non-empty list means node_modules exists but is half-installed, which is
    real drift between package.json and the tree the suites import from. None
    means node_modules is absent entirely: it is gitignored, so a fresh clone
    or git worktree starts without it and there is no install to compare
    against. Absent is unchecked, not clean, and the caller has to say which.
    """
    package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    names = list(package.get("dependencies") or {})
    names += list(package.get("devDependencies") or {})
    if not names:
        raise ValueError(f"{root / 'package.json'} declares no Node packages")
    modules = root / "node_modules"
    if not modules.is_dir():
        return None
    return [name for name in names if not (modules / Path(*name.split("/"))).is_dir()]


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


class TestAbsentDeclaredPackages(unittest.TestCase):
    def test_fully_installed_tree_is_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _fake_repo(
                Path(tmp) / "repo",
                package={"devDependencies": {"@scope/pkg": "^1.0.0"}},
                installed=["@scope/pkg"],
            )
            self.assertEqual(absent_declared_packages(repo), [])

    def test_half_installed_tree_names_the_missing_packages(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _fake_repo(
                Path(tmp) / "repo",
                package={
                    "devDependencies": {"@scope/here": "^1.0.0", "@scope/gone": "^1.0.0"}
                },
                installed=["@scope/here"],
            )
            self.assertEqual(absent_declared_packages(repo), ["@scope/gone"])

    def test_absent_node_modules_is_unchecked_not_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _fake_repo(
                Path(tmp) / "repo",
                package={"devDependencies": {"@scope/pkg": "^1.0.0"}},
                installed=[],
            )
            self.assertIsNone(absent_declared_packages(repo))


class TestRealRepoToolchain(unittest.TestCase):
    def test_every_declared_node_package_is_present_in_this_checkout(self):
        missing = absent_declared_packages(REPO_ROOT)
        if missing is None:
            raise unittest.SkipTest(
                f"unchecked: {REPO_ROOT / 'node_modules'} is absent, so nothing is "
                "installed to drift from package.json. scripts/run_all_tests.sh is "
                "the documented test command and installs it; bare 'unittest "
                "discover' skips that gate."
            )
        self.assertEqual(
            missing,
            [],
            f"node_modules in {REPO_ROOT} is half-installed; run 'npm ci' there",
        )


if __name__ == "__main__":
    unittest.main()
