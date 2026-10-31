#!/usr/bin/env python3
"""Positive + negative tests for the plutil shim and its bootstrap.

scripts/install ships launchd plists whose proof commands run
`plutil -lint <path>`, and only macOS ships plutil, so on Linux that proof
died with "plutil: command not found". The negative controls are the point:
a plist that does not parse, a flag the shim does not implement, and a host
with nowhere on PATH to install the shim must each exit non-zero with a named
reason, never report a pass over a plist nothing checked.
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
BOOTSTRAP = REPO / "scripts" / "test" / "ensure_plutil_toolchain.sh"
SHIM = REPO / "scripts" / "test" / "plutil_lint.py"
RUNNER = REPO / "scripts" / "test" / "run_all_tests.sh"
PLIST = REPO / "scripts" / "install" / "com.catstack.lifecycle.plist"
BASH = shutil.which("bash") or "/bin/bash"
PYTHON3 = shutil.which("python3") or "/usr/bin/python3"
BASE_PATH = os.environ.get("PATH", "/usr/bin:/bin")

GOOD_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.example.job</string>
</dict>
</plist>
"""
BAD_PLIST = '<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict><key>Label</key>\n'


def _fake_repo(tmp: str, *, with_shim: bool = True) -> Path:
    root = Path(tmp) / "repo"
    (root / "scripts" / "test").mkdir(parents=True)
    (root / "scripts" / "test" / "ensure_plutil_toolchain.sh").write_text(
        BOOTSTRAP.read_text(encoding="utf-8"), encoding="utf-8"
    )
    if with_shim:
        (root / "scripts" / "test" / "plutil_lint.py").write_text(
            SHIM.read_text(encoding="utf-8"), encoding="utf-8"
        )
    return root


def _stub(bindir: Path, name: str, body: str) -> None:
    bindir.mkdir(parents=True, exist_ok=True)
    stub = bindir / name
    stub.write_text(body, encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)


def _run_bootstrap(root: Path, *, path: str, bin_dir: str | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ, PATH=path)
    if bin_dir is None:
        env.pop("CATSTACK_PLUTIL_BIN_DIR", None)
    else:
        env["CATSTACK_PLUTIL_BIN_DIR"] = bin_dir
    return subprocess.run(
        [BASH, str(root / "scripts" / "test" / "ensure_plutil_toolchain.sh")],
        capture_output=True,
        text=True,
        env=env,
    )


def _run_shim(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PYTHON3, str(SHIM), *args], capture_output=True, text=True
    )


class PlutilShimTest(unittest.TestCase):
    def test_lints_the_shipped_lifecycle_plist(self):
        result = _run_shim("-lint", str(PLIST))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OK", result.stdout)

    def test_malformed_plist_exits_nonzero_with_a_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.plist"
            bad.write_text(BAD_PLIST, encoding="utf-8")
            result = _run_shim("-lint", str(bad))
        self.assertEqual(result.returncode, 1)
        self.assertIn("bad.plist", result.stderr)

    def test_missing_file_exits_nonzero(self):
        result = _run_shim("-lint", "/nonexistent/none.plist")
        self.assertEqual(result.returncode, 1)
        self.assertIn("does not exist", result.stderr)

    def test_unsupported_flag_refuses_instead_of_passing(self):
        result = _run_shim("-convert", "xml1", str(PLIST))
        self.assertEqual(result.returncode, 2)
        self.assertIn("only `-lint", result.stderr)

    def test_lint_without_a_file_refuses(self):
        result = _run_shim("-lint")
        self.assertEqual(result.returncode, 2)
        self.assertIn("no file was given", result.stderr)


class EnsurePlutilToolchainTest(unittest.TestCase):
    def test_installs_a_working_plutil_when_none_is_on_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _fake_repo(tmp)
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            result = _run_bootstrap(root, path=BASE_PATH, bin_dir=str(bin_dir))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("plutil shim installed", result.stdout)
            installed = bin_dir / "plutil"
            self.assertTrue(os.access(installed, os.X_OK))
            good = Path(tmp) / "good.plist"
            good.write_text(GOOD_PLIST, encoding="utf-8")
            linted = subprocess.run(
                [str(installed), "-lint", str(good)], capture_output=True, text=True
            )
            self.assertEqual(linted.returncode, 0, linted.stderr)

    def test_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _fake_repo(tmp)
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            first = _run_bootstrap(root, path=BASE_PATH, bin_dir=str(bin_dir))
            second = _run_bootstrap(root, path=BASE_PATH, bin_dir=str(bin_dir))
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)

    def test_leaves_an_existing_plutil_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _fake_repo(tmp)
            bindir = Path(tmp) / "hostbin"
            _stub(bindir, "plutil", "#!/bin/sh\nexit 0\n")
            target = Path(tmp) / "bin"
            target.mkdir()
            result = _run_bootstrap(
                root, path=f"{bindir}:{BASE_PATH}", bin_dir=str(target)
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("already on PATH", result.stdout)
            self.assertFalse((target / "plutil").exists())

    def test_skips_macos_so_it_never_shadows_apple_plutil(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _fake_repo(tmp)
            bindir = Path(tmp) / "darwinbin"
            _stub(bindir, "uname", "#!/bin/sh\necho Darwin\n")
            target = Path(tmp) / "bin"
            target.mkdir()
            result = _run_bootstrap(
                root, path=f"{bindir}:{BASE_PATH}", bin_dir=str(target)
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("macOS ships plutil", result.stdout)
            self.assertFalse((target / "plutil").exists())

    def test_missing_shim_source_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _fake_repo(tmp, with_shim=False)
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            result = _run_bootstrap(root, path=BASE_PATH, bin_dir=str(bin_dir))
        self.assertEqual(result.returncode, 1)
        self.assertIn("plutil_lint.py is missing", result.stderr)

    def test_unwritable_target_exits_nonzero_with_a_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _fake_repo(tmp)
            locked = Path(tmp) / "locked"
            locked.mkdir(mode=0o500)
            try:
                result = _run_bootstrap(root, path=BASE_PATH, bin_dir=str(locked))
            finally:
                locked.chmod(0o700)
        self.assertEqual(result.returncode, 1)
        self.assertIn("plutil", result.stderr)

    def test_no_writable_path_directory_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _fake_repo(tmp)
            locked = Path(tmp) / "onlybin"
            locked.mkdir()
            for tool in ("uname", "python3", "cp", "chmod", "mkdir", "dirname", "tr", "printf"):
                found = shutil.which(tool)
                if found:
                    (locked / tool).symlink_to(found)
            locked.chmod(0o500)
            try:
                result = _run_bootstrap(root, path=str(locked))
            finally:
                locked.chmod(0o700)
        self.assertEqual(result.returncode, 1)
        self.assertIn("no writable directory on PATH", result.stderr)


class RunnerWiringTest(unittest.TestCase):
    def test_run_all_tests_runs_the_bootstrap_before_the_suites(self):
        text = RUNNER.read_text(encoding="utf-8")
        self.assertIn("bash scripts/test/ensure_plutil_toolchain.sh || status=1", text)
        self.assertLess(
            text.index("ensure_plutil_toolchain.sh"), text.index("unittest discover")
        )


if __name__ == "__main__":
    unittest.main()
