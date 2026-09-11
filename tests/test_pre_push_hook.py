#!/usr/bin/env python3
"""Tests for scripts/git-hooks/pre-push and scripts/install-git-hooks.sh.

Each case builds a bare remote and a clone whose origin/main carries this
repo's preflight.py, pre-push hook, and installer byte-for-byte, runs the
installer, and pushes a real branch through the installed hook.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from git_test_repo import init_repo  # noqa: E402

SHIPPED = (
    "engine/skills/make-pr/scripts/preflight.py",
    "scripts/git-hooks/pre-push",
    "scripts/install-git-hooks.sh",
)
UNCHECKED_LINE = (
    "pre-push: UNCHECKED: origin/main not found; run git fetch origin main, "
    "or push with --no-verify to bypass"
)
FOREIGN_HOOK = b"#!/bin/sh\necho someone else's hook\nexit 0\n"


class Sandbox:
    def __init__(self, root: Path, install: bool = True):
        self.root = root
        self.hook_tmp = root / "hook-tmp"
        self.hook_tmp.mkdir()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_NOSYSTEM="1",
            GIT_AUTHOR_NAME="T",
            GIT_AUTHOR_EMAIL="t@example.invalid",
            GIT_COMMITTER_NAME="T",
            GIT_COMMITTER_EMAIL="t@example.invalid",
            TMPDIR=str(self.hook_tmp),
        )
        self.remote = root / "remote.git"
        self.clone = root / "clone"
        init_repo(self.remote, "--bare", "-b", "main", env=self.env)
        init_repo(self.clone, "-b", "main", env=self.env)
        for rel in SHIPPED:
            dest = self.clone / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / rel, dest)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "main")
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "-q", "origin", "main")
        self.git("fetch", "-q", "origin")
        self.hook = Path(self.git("rev-parse", "--git-path", "hooks").stdout.strip())
        if not self.hook.is_absolute():
            self.hook = self.clone / self.hook
        self.hook = self.hook / "pre-push"
        if install:
            res = self.install()
            assert res.returncode == 0, res.stdout + res.stderr

    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(self.clone), *args],
            capture_output=True, text=True, env=self.env, check=check,
        )

    def install(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(self.clone / "scripts/install-git-hooks.sh")],
            cwd=self.clone, capture_output=True, text=True, env=self.env,
        )

    def branch(self, name: str, paths: tuple[str, ...]) -> None:
        self.git("checkout", "-q", "-b", name, "main")
        for rel in paths:
            dest = self.clone / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(f"{rel}\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", name)

    def push(self, *args: str) -> subprocess.CompletedProcess:
        return self.git("push", "origin", *args, check=False)

    def remote_has(self, branch: str) -> bool:
        out = subprocess.run(
            ["git", "-C", str(self.remote), "rev-parse", "--verify", "-q", f"refs/heads/{branch}"],
            capture_output=True, text=True, env=self.env,
        )
        return out.returncode == 0


MIXED = ("engine/hooks/x/detect.py", "product/skills/y/run.py")
SINGLE = ("scripts/z.sh", "tests/test_z.py")


class TestPrePushHook(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_mixed_engine_and_product_skill_push_is_refused(self):
        box = Sandbox(self.root)
        box.branch("mixed", MIXED)
        status_before = box.git("status", "--porcelain").stdout
        res = box.push("mixed")
        self.assertNotEqual(res.returncode, 0, res.stderr)
        self.assertIn("more than one review unit", res.stderr)
        self.assertIn("pre-push: refusing refs/heads/mixed: make one branch per review unit", res.stderr)
        self.assertFalse(box.remote_has("mixed"))
        self.assertEqual(box.git("status", "--porcelain").stdout, status_before)
        self.assertEqual(os.listdir(box.hook_tmp), [])

    def test_mixed_push_through_head_refspec_is_refused(self):
        box = Sandbox(self.root)
        box.branch("mixed", MIXED)
        res = box.push("HEAD:topic")
        self.assertNotEqual(res.returncode, 0, res.stderr)
        self.assertIn("more than one review unit", res.stderr)
        self.assertFalse(box.remote_has("topic"))

    def test_scripts_plus_tests_push_is_accepted(self):
        box = Sandbox(self.root)
        box.branch("single", SINGLE)
        res = box.push("single")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(box.remote_has("single"))
        self.assertEqual(os.listdir(box.hook_tmp), [])

    def test_branch_deletion_push_is_accepted(self):
        box = Sandbox(self.root)
        box.branch("mixed", MIXED)
        self.assertEqual(box.push("--no-verify", "mixed").returncode, 0)
        self.assertTrue(box.remote_has("mixed"))
        res = box.push(":mixed")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertFalse(box.remote_has("mixed"))

    def test_missing_origin_main_is_refused_as_unchecked(self):
        box = Sandbox(self.root)
        box.branch("single", SINGLE)
        box.git("update-ref", "-d", "refs/remotes/origin/main")
        res = box.push("single")
        self.assertNotEqual(res.returncode, 0, res.stderr)
        self.assertIn(UNCHECKED_LINE, res.stderr)
        self.assertFalse(box.remote_has("single"))


class TestInstaller(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_installer_refuses_a_foreign_pre_push_hook(self):
        box = Sandbox(self.root, install=False)
        box.hook.parent.mkdir(parents=True, exist_ok=True)
        box.hook.write_bytes(FOREIGN_HOOK)
        res = box.install()
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("exists and was not written by catstack; leaving it alone", res.stderr)
        self.assertEqual(box.hook.read_bytes(), FOREIGN_HOOK)

    def test_installer_rerun_over_its_own_hook_succeeds(self):
        box = Sandbox(self.root)
        res = box.install()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(box.hook.read_bytes(), (REPO / "scripts/git-hooks/pre-push").read_bytes())
        self.assertTrue(os.access(box.hook, os.X_OK))


if __name__ == "__main__":
    unittest.main()
