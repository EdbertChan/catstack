#!/usr/bin/env python3
"""Positive + negative tests for scripts/run_all_tests.sh's Node toolchain step.

CONTRIBUTING names `bash scripts/run_all_tests.sh` as the whole test command,
but two suites shell out to Node packages that only exist after `npm ci`. A
fresh clone or git worktree has no node_modules, so those suites used to fail
on ERR_MODULE_NOT_FOUND -- a dependency error wearing the costume of a real
defect. The runner now installs the toolchain itself, and when it cannot
(no npm, unreadable manifest, install that leaves the tree incomplete) it
refuses out loud instead of running a suite whose verdict would be a lie.

Every case here drives the real script inside a throwaway repo on a sealed
PATH, so no test needs the network or the developer's own node_modules.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUNNER = REPO / "scripts" / "run_all_tests.sh"

SEALED_TOOLS = ("bash", "python3", "find", "sort", "dirname", "mkdir")

PASSING_SUITE = """import unittest


class TestSample(unittest.TestCase):
    def test_sample_suite_ran(self):
        self.assertTrue(True)
"""

FAKE_NPM = """#!/bin/bash
printf '%s\\n' "$*" >> "$NPM_CALL_LOG"
mkdir -p "$NPM_INSTALL_TARGET"
printf '{"name": "installed"}\\n' > "$NPM_INSTALL_TARGET/package.json"
"""

FAILING_NPM = """#!/bin/bash
printf '%s\\n' "$*" >> "$NPM_CALL_LOG"
echo "npm blew up" >&2
exit 1
"""


class RunnerHarness:
    """A throwaway repo holding a copy of the real runner and one Python suite."""

    def __init__(self, tmp: str):
        self.root = Path(tmp) / "repo"
        (self.root / "scripts").mkdir(parents=True)
        self.script = self.root / "scripts" / "run_all_tests.sh"
        self.script.write_text(RUNNER.read_text(encoding="utf-8"), encoding="utf-8")
        (self.root / "tests").mkdir()
        (self.root / "tests" / "test_sample.py").write_text(PASSING_SUITE, encoding="utf-8")
        self.bin = Path(tmp) / "bin"
        self.bin.mkdir()
        for tool in SEALED_TOOLS:
            (self.bin / tool).symlink_to(self._which(tool))
        self.npm_log = Path(tmp) / "npm-calls.log"
        self.install_target = self.root / "node_modules" / "unused"

    @staticmethod
    def _which(tool: str) -> str:
        found = shutil.which(tool)
        if not found:
            raise unittest.SkipTest(f"{tool} is not installed, so the sealed PATH cannot be built")
        return found

    def declare_dependency(self, name: str = "@example/toolchain", with_lockfile: bool = True) -> None:
        (self.root / "package.json").write_text(
            json.dumps({"name": "harness", "devDependencies": {name: "^1.0.0"}}), encoding="utf-8"
        )
        if with_lockfile:
            (self.root / "package-lock.json").write_text("{}\n", encoding="utf-8")

    def install_dependency(self, name: str = "@example/toolchain") -> None:
        package = self.root / "node_modules" / name
        package.mkdir(parents=True)
        (package / "package.json").write_text('{"name": "installed"}\n', encoding="utf-8")

    def add_npm(self, body: str, install_target: str = "@example/toolchain") -> None:
        npm = self.bin / "npm"
        npm.write_text(body, encoding="utf-8")
        npm.chmod(0o755)
        self.install_target = self.root / "node_modules" / install_target

    def run(self) -> subprocess.CompletedProcess:
        env = {
            "PATH": str(self.bin),
            "HOME": str(self.root),
            "NPM_CALL_LOG": str(self.npm_log),
            "NPM_INSTALL_TARGET": str(self.install_target),
        }
        return subprocess.run(
            [str(self.bin / "bash"), str(self.script)],
            capture_output=True, text=True, env=env, timeout=120,
        )

    def npm_calls(self) -> list[str]:
        if not self.npm_log.exists():
            return []
        return [line for line in self.npm_log.read_text(encoding="utf-8").splitlines() if line]


class TestNodeToolchainBootstrap(unittest.TestCase):
    def test_missing_package_is_installed_then_the_python_suites_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness = RunnerHarness(tmp)
            harness.declare_dependency()
            harness.add_npm(FAKE_NPM)
            result = harness.run()
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(harness.npm_calls(), ["ci"])
            self.assertIn("test_sample_suite_ran", result.stderr + result.stdout)

    def test_without_a_lockfile_it_installs_rather_than_running_npm_ci(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness = RunnerHarness(tmp)
            harness.declare_dependency(with_lockfile=False)
            harness.add_npm(FAKE_NPM)
            result = harness.run()
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(harness.npm_calls(), ["install"])

    def test_a_complete_tree_runs_the_suites_without_touching_npm(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness = RunnerHarness(tmp)
            harness.declare_dependency()
            harness.install_dependency()
            harness.add_npm(FAILING_NPM)
            result = harness.run()
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(harness.npm_calls(), [])
            self.assertIn("test_sample_suite_ran", result.stderr + result.stdout)

    def test_a_repo_with_no_package_json_still_runs_the_suites(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness = RunnerHarness(tmp)
            result = harness.run()
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn("test_sample_suite_ran", result.stderr + result.stdout)


class TestUnrunnableIsNotAPass(unittest.TestCase):
    """The third outcome: the toolchain check that cannot run says so."""

    def test_absent_npm_refuses_instead_of_running_the_suites(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness = RunnerHarness(tmp)
            harness.declare_dependency()
            result = harness.run()
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("unchecked", result.stderr)
            self.assertIn("@example/toolchain", result.stderr)
            self.assertNotIn("test_sample_suite_ran", result.stderr + result.stdout)

    def test_failing_install_refuses_instead_of_running_the_suites(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness = RunnerHarness(tmp)
            harness.declare_dependency()
            harness.add_npm(FAILING_NPM)
            result = harness.run()
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("unchecked", result.stderr)
            self.assertEqual(harness.npm_calls(), ["ci"])
            self.assertNotIn("test_sample_suite_ran", result.stderr + result.stdout)

    def test_install_that_leaves_the_tree_incomplete_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness = RunnerHarness(tmp)
            harness.declare_dependency()
            harness.add_npm(FAKE_NPM, install_target="@example/something-else")
            result = harness.run()
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("still not ready", result.stderr)
            self.assertNotIn("test_sample_suite_ran", result.stderr + result.stdout)

    def test_unreadable_package_json_refuses_instead_of_reporting_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness = RunnerHarness(tmp)
            (harness.root / "package.json").write_text("{not json at all", encoding="utf-8")
            harness.add_npm(FAKE_NPM)
            result = harness.run()
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("unchecked", result.stderr)
            self.assertEqual(harness.npm_calls(), [])
            self.assertNotIn("test_sample_suite_ran", result.stderr + result.stdout)


class TestRealRepositoryDeclaresItsNodeToolchain(unittest.TestCase):
    def test_the_two_node_backed_scripts_import_a_declared_dependency(self):
        manifest = json.loads((REPO / "package.json").read_text(encoding="utf-8"))
        declared = set(manifest.get("dependencies", {})) | set(manifest.get("devDependencies", {}))
        self.assertTrue(declared, "package.json declares no Node dependency to install")
        for relative in ("engine/skills/draft-pr/scripts/validate-pr-body.mjs",):
            source = (REPO / relative).read_text(encoding="utf-8")
            self.assertTrue(
                any(f"'{name}'" in source or f'"{name}"' in source for name in declared),
                f"{relative} imports a package that package.json does not declare",
            )


if __name__ == "__main__":
    unittest.main()
