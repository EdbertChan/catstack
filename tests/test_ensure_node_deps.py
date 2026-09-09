#!/usr/bin/env python3
"""Positive + negative tests for scripts/ensure_node_deps.sh.

engine/skills/draft-pr's tests shell out to Node scripts that import the
committed drafter-core devDependency. CI installs it in a separate `npm ci`
step, so a fresh clone or git worktree -- which has no node_modules -- failed
those two tests with ERR_MODULE_NOT_FOUND even though nothing was wrong with
the code under test. This bootstrap is what makes `bash scripts/run_all_tests.sh`,
the documented single entry point, carry that step itself.

The sandbox PATH holds only the stub npm and the one external tool the script
itself needs, so the real npm can never leak into the missing-npm case.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "ensure_node_deps.sh"
BASH = shutil.which("bash") or "/bin/bash"

RECORDING_NPM = """#!/bin/bash
echo "$@" >> "$NPM_CALLS"
"""

FAILING_NPM = """#!/bin/bash
echo "registry unreachable" >&2
exit 1
"""


class _Result:
    def __init__(self, proc: subprocess.CompletedProcess, calls: list[str]) -> None:
        self.proc = proc
        self.calls = calls


def _run(tmp: Path, *, npm_stub: str | None, node_modules: bool, package_json: bool = True) -> _Result:
    (tmp / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, tmp / "scripts" / SCRIPT.name)
    if package_json:
        (tmp / "package.json").write_text('{"name": "fake", "private": true}\n', encoding="utf-8")
        (tmp / "package-lock.json").write_text('{"lockfileVersion": 3}\n', encoding="utf-8")
    if node_modules:
        (tmp / "node_modules").mkdir()

    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    tools_dir = tmp / "tools"
    tools_dir.mkdir()
    for tool in ("dirname",):
        real = shutil.which(tool)
        assert real, f"{tool} must exist for the sandbox PATH"
        (tools_dir / tool).symlink_to(real)
    if npm_stub is not None:
        npm = bin_dir / "npm"
        npm.write_text(npm_stub, encoding="utf-8")
        npm.chmod(0o755)

    calls_file = tmp / "npm-calls.txt"
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{tools_dir}"
    env["NPM_CALLS"] = str(calls_file)
    proc = subprocess.run(
        [BASH, str(tmp / "scripts" / SCRIPT.name)],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    calls = calls_file.read_text(encoding="utf-8").split("\n") if calls_file.exists() else []
    return _Result(proc, [line for line in calls if line])


class TestEnsureNodeDeps(unittest.TestCase):
    def test_missing_node_modules_runs_npm_ci(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(Path(tmp), npm_stub=RECORDING_NPM, node_modules=False)
        self.assertEqual(result.proc.returncode, 0, result.proc.stderr + result.proc.stdout)
        self.assertEqual(result.calls, ["ci"])

    def test_present_node_modules_installs_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(Path(tmp), npm_stub=RECORDING_NPM, node_modules=True)
        self.assertEqual(result.proc.returncode, 0, result.proc.stderr + result.proc.stdout)
        self.assertEqual(result.calls, [])
        self.assertIn("already present", result.proc.stdout)

    def test_no_package_json_is_a_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(Path(tmp), npm_stub=RECORDING_NPM, node_modules=False, package_json=False)
        self.assertEqual(result.proc.returncode, 0, result.proc.stderr + result.proc.stdout)
        self.assertEqual(result.calls, [])

    def test_missing_npm_fails_loudly_instead_of_passing(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(Path(tmp), npm_stub=None, node_modules=False)
        self.assertEqual(result.proc.returncode, 1, result.proc.stdout)
        self.assertIn("npm is not on PATH", result.proc.stderr)

    def test_failed_install_is_reported_not_swallowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(Path(tmp), npm_stub=FAILING_NPM, node_modules=False)
        self.assertEqual(result.proc.returncode, 1, result.proc.stdout)
        self.assertIn("registry unreachable", result.proc.stderr)
        self.assertIn("npm ci' failed", result.proc.stderr)


class TestRunAllTestsCallsBootstrap(unittest.TestCase):
    def test_entry_point_bootstraps_before_discovering_suites(self):
        text = (REPO_ROOT / "scripts" / "run_all_tests.sh").read_text(encoding="utf-8")
        self.assertIn("scripts/ensure_node_deps.sh", text)
        self.assertLess(text.index("ensure_node_deps.sh"), text.index("unittest discover"))


if __name__ == "__main__":
    unittest.main()
