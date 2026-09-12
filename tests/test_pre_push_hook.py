#!/usr/bin/env python3
"""Tests for scripts/git-hooks/pre-push and scripts/install-git-hooks.sh.

Each case builds a bare remote and a clone whose origin/main carries this
repo's preflight.py, pre-push hook, and installer byte-for-byte, runs the
installer, and pushes a real branch through the installed hook. origin is a
GitHub URL that insteadOf rewrites to the bare remote, and a fake gh on PATH
answers the hook's open-PR lookup, so no case talks to GitHub.
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
CATSTACK_URL = "https://github.com/EdbertChan/catstack.git"
UNCHECKED_LINE = (
    "pre-push: UNCHECKED: origin/main not found; run git fetch origin main, "
    "or push with --no-verify to bypass"
)
FOREIGN_HOOK = b"#!/bin/sh\necho someone else's hook\nexit 0\n"
FAKE_GH = """#!/bin/sh
printf '%s\\n' "$*" >>"$FAKE_GH_LOG"
case "$FAKE_GH" in
  fail) echo "gh: could not reach api.github.com" >&2; exit 1 ;;
  none) exit 0 ;;
  base:*) echo "${FAKE_GH#base:}" ;;
esac
"""


def change_id(seed: str) -> str:
    return "I" + (seed * 40)[:40]


class Sandbox:
    def __init__(self, root: Path, install: bool = True, gh: str = "none"):
        self.root = root
        self.hook_tmp = root / "hook-tmp"
        self.hook_tmp.mkdir()
        bin_dir = root / "bin"
        bin_dir.mkdir()
        fake_gh = bin_dir / "gh"
        fake_gh.write_text(FAKE_GH, encoding="utf-8")
        fake_gh.chmod(0o755)
        self.gh_log = root / "gh.log"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_NOSYSTEM="1",
            GIT_AUTHOR_NAME="T",
            GIT_AUTHOR_EMAIL="t@example.invalid",
            GIT_COMMITTER_NAME="T",
            GIT_COMMITTER_EMAIL="t@example.invalid",
            TMPDIR=str(self.hook_tmp),
            PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            FAKE_GH=gh,
            FAKE_GH_LOG=str(self.gh_log),
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
        self.git("remote", "add", "origin", CATSTACK_URL)
        self.git("config", f"url.{self.remote}.insteadOf", CATSTACK_URL)
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

    def gh(self, mode: str) -> None:
        self.env["FAKE_GH"] = mode

    def commit(self, paths: tuple[str, ...], message: str, cid: str | None = None) -> None:
        for rel in paths:
            dest = self.clone / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(f"{rel}\n", encoding="utf-8")
        self.git("add", "-A")
        extra = ("-m", f"Change-Id: {cid}") if cid else ()
        self.git("commit", "-q", "-m", message, *extra)

    def branch(self, name: str, paths: tuple[str, ...], start: str = "main", cid: str | None = None) -> None:
        self.git("checkout", "-q", "-b", name, start)
        self.commit(paths, name, cid)

    def push(self, *args: str) -> subprocess.CompletedProcess:
        return self.git("push", "origin", *args, check=False)

    def remote_has(self, branch: str) -> bool:
        out = subprocess.run(
            ["git", "-C", str(self.remote), "rev-parse", "--verify", "-q", f"refs/heads/{branch}"],
            capture_output=True, text=True, env=self.env,
        )
        return out.returncode == 0

    def gh_calls(self) -> str:
        return self.gh_log.read_text(encoding="utf-8") if self.gh_log.exists() else ""


MIXED = ("engine/hooks/x/detect.py", "product/skills/y/run.py")
ENGINE = ("engine/hooks/x/detect.py",)
SKILL = ("product/skills/y/run.py",)
OTHER_SKILL = ("product/skills/z/SKILL.md",)
SINGLE = ("scripts/z.sh", "tests/test_z.py")
REFUSED = "pre-push: refusing refs/heads/{}: make one branch per review unit"
CHECKED_FROM = REFUSED + ", checked from {}"


class TestPrBranches(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_mixed_push_to_a_branch_with_an_open_pr_is_refused(self):
        box = Sandbox(self.root, gh="base:main")
        box.branch("mixed", MIXED)
        status_before = box.git("status", "--porcelain").stdout
        res = box.push("mixed")
        self.assertNotEqual(res.returncode, 0, res.stderr)
        self.assertIn("more than one review unit", res.stderr)
        self.assertIn(REFUSED.format("mixed"), res.stderr)
        self.assertFalse(box.remote_has("mixed"))
        self.assertIn("--repo EdbertChan/catstack --head mixed --state open", box.gh_calls())
        self.assertEqual(box.git("status", "--porcelain").stdout, status_before)
        self.assertEqual(os.listdir(box.hook_tmp), [])

    def test_mixed_push_through_head_refspec_to_a_pr_branch_is_refused(self):
        box = Sandbox(self.root, gh="base:main")
        box.branch("mixed", MIXED)
        res = box.push("HEAD:topic")
        self.assertNotEqual(res.returncode, 0, res.stderr)
        self.assertIn("more than one review unit", res.stderr)
        self.assertIn("--head topic ", box.gh_calls())
        self.assertFalse(box.remote_has("topic"))

    def test_scripts_plus_tests_push_to_a_pr_branch_is_accepted(self):
        box = Sandbox(self.root, gh="base:main")
        box.branch("single", SINGLE)
        res = box.push("single")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(box.remote_has("single"))
        self.assertEqual(os.listdir(box.hook_tmp), [])

    def test_pr_on_a_stacked_base_is_checked_from_that_base(self):
        box = Sandbox(self.root)
        box.branch("lower", ENGINE)
        self.assertEqual(box.push("--no-verify", "lower").returncode, 0)
        box.git("fetch", "-q", "origin")
        box.branch("upper", SKILL, start="lower")
        box.gh("base:lower")
        res = box.push("upper")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(box.remote_has("upper"))

    def test_pr_base_not_fetched_is_checked_against_origin_main(self):
        box = Sandbox(self.root, gh="base:lower")
        box.branch("lower", ENGINE)
        box.branch("upper", SKILL, start="lower")
        res = box.push("upper")
        self.assertNotEqual(res.returncode, 0, res.stderr)
        self.assertIn("pre-push: note: origin/lower is not fetched; checking refs/heads/upper against origin/main", res.stderr)
        self.assertIn(REFUSED.format("upper"), res.stderr)

    def test_missing_origin_main_on_a_pr_branch_is_refused_as_unchecked(self):
        box = Sandbox(self.root, gh="base:main")
        box.branch("single", SINGLE)
        box.git("update-ref", "-d", "refs/remotes/origin/main")
        res = box.push("single")
        self.assertNotEqual(res.returncode, 0, res.stderr)
        self.assertIn(UNCHECKED_LINE, res.stderr)
        self.assertFalse(box.remote_has("single"))

    def test_branch_deletion_push_is_accepted(self):
        box = Sandbox(self.root, gh="base:main")
        box.branch("mixed", MIXED)
        self.assertEqual(box.push("--no-verify", "mixed").returncode, 0)
        self.assertTrue(box.remote_has("mixed"))
        res = box.push(":mixed")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertFalse(box.remote_has("mixed"))


class TestBranchesWithoutAPr(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_invoker_experiment_branch_with_mixed_units_is_pushed(self):
        box = Sandbox(self.root)
        box.branch("experiment/wf-1/repair/g0.t0.a-1", MIXED)
        res = box.push("experiment/wf-1/repair/g0.t0.a-1")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("review unit", res.stderr)
        self.assertTrue(box.remote_has("experiment/wf-1/repair/g0.t0.a-1"))
        self.assertIn("--head experiment/wf-1/repair/g0.t0.a-1 ", box.gh_calls())
        self.assertEqual(os.listdir(box.hook_tmp), [])

    def test_branch_without_a_pr_needs_no_origin_main(self):
        box = Sandbox(self.root)
        box.branch("scratch", MIXED)
        box.git("update-ref", "-d", "refs/remotes/origin/main")
        res = box.push("scratch")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(box.remote_has("scratch"))

    def test_failed_pr_lookup_is_reported_and_the_push_goes_through(self):
        box = Sandbox(self.root, gh="fail")
        box.branch("experiment/x", MIXED)
        res = box.push("experiment/x")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(
            "pre-push: UNCHECKED: could not look up an open PR for experiment/x on EdbertChan/catstack: "
            "gh: could not reach api.github.com; pushing without the review-unit check",
            res.stderr,
        )
        self.assertTrue(box.remote_has("experiment/x"))

    def test_non_github_remote_is_not_looked_up(self):
        box = Sandbox(self.root)
        box.git("remote", "set-url", "origin", str(box.remote))
        box.branch("topic", MIXED)
        res = box.push("topic")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(box.gh_calls(), "")


class TestMergifyStackBranches(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_stack_branch_without_a_pr_yet_is_refused_when_mixed(self):
        box = Sandbox(self.root)
        box.branch("stack/T/topic/one", MIXED)
        res = box.push("stack/T/topic/one")
        self.assertNotEqual(res.returncode, 0, res.stderr)
        self.assertIn(CHECKED_FROM.format("stack/T/topic/one", "origin/main"), res.stderr)
        self.assertFalse(box.remote_has("stack/T/topic/one"))

    def test_stack_branch_is_checked_even_when_the_pr_lookup_fails(self):
        box = Sandbox(self.root, gh="fail")
        box.branch("stack/T/topic/one", MIXED)
        res = box.push("stack/T/topic/one")
        self.assertNotEqual(res.returncode, 0, res.stderr)
        self.assertIn(
            "pre-push: note: could not look up an open PR for stack/T/topic/one on EdbertChan/catstack: "
            "gh: could not reach api.github.com; checking it against origin/main",
            res.stderr,
        )
        self.assertIn(REFUSED.format("stack/T/topic/one"), res.stderr)

    def test_mergify_stack_commit_is_checked_alone_against_its_parent(self):
        box = Sandbox(self.root)
        box.branch("stack/T/topic/engine--aaaaaaaa", ENGINE, cid=change_id("a"))
        box.commit(SKILL, "skill", change_id("b"))
        res = box.push("HEAD:refs/heads/stack/T/topic/skill--bbbbbbbb")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(box.remote_has("stack/T/topic/skill--bbbbbbbb"))
        self.assertEqual(box.gh_calls(), "")

    def test_mergify_stack_commit_that_mixes_units_is_refused(self):
        box = Sandbox(self.root)
        box.branch("stack/T/topic/mixed--cccccccc", MIXED, cid=change_id("c"))
        res = box.push("stack/T/topic/mixed--cccccccc")
        self.assertNotEqual(res.returncode, 0, res.stderr)
        self.assertIn(REFUSED.format("stack/T/topic/mixed--cccccccc"), res.stderr)

    def test_configured_mergify_prefix_is_a_stack_branch(self):
        box = Sandbox(self.root)
        box.git("config", "mergify-cli.stack-branch-prefix", "stacks/me")
        box.branch("stacks/me/topic/one", MIXED)
        res = box.push("stacks/me/topic/one")
        self.assertNotEqual(res.returncode, 0, res.stderr)
        self.assertIn(REFUSED.format("stacks/me/topic/one"), res.stderr)


class TestStackedOnAPushedBranch(unittest.TestCase):
    """A branch with no PR yet is checked from the pushed branch it sits on."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def stacked(self, box: Sandbox, paths: tuple[str, ...]) -> subprocess.CompletedProcess:
        box.branch("stack/T/topic/lower", SKILL)
        assert box.push("stack/T/topic/lower").returncode == 0
        box.git("fetch", "-q", "origin")
        box.branch("stack/T/topic/upper", paths, start="stack/T/topic/lower")
        return box.push("stack/T/topic/upper")

    def test_stack_branch_on_a_pushed_parent_carries_no_parent_files(self):
        box = Sandbox(self.root)
        res = self.stacked(box, ENGINE)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(box.remote_has("stack/T/topic/upper"))
        self.assertEqual(os.listdir(box.hook_tmp), [])

    def test_stack_branch_that_mixes_units_above_its_parent_is_refused(self):
        box = Sandbox(self.root)
        res = self.stacked(box, ENGINE + OTHER_SKILL)
        self.assertNotEqual(res.returncode, 0, res.stderr)
        self.assertIn(
            CHECKED_FROM.format("stack/T/topic/upper", "origin/stack/T/topic/lower"),
            res.stderr,
        )
        self.assertFalse(box.remote_has("stack/T/topic/upper"))

    def test_a_pr_based_on_main_is_still_checked_from_main(self):
        box = Sandbox(self.root)
        box.gh("base:main")
        res = self.stacked(box, ENGINE)
        self.assertNotEqual(res.returncode, 0, res.stderr)
        self.assertIn(CHECKED_FROM.format("stack/T/topic/upper", "origin/main"), res.stderr)

    def test_second_push_of_a_branch_is_not_checked_from_its_own_last_push(self):
        box = Sandbox(self.root)
        box.branch("stack/T/topic/one", SKILL)
        self.assertEqual(box.push("stack/T/topic/one").returncode, 0)
        box.git("fetch", "-q", "origin")
        box.commit(ENGINE, "add engine files")
        res = box.push("stack/T/topic/one")
        self.assertNotEqual(res.returncode, 0, res.stderr)
        self.assertIn(CHECKED_FROM.format("stack/T/topic/one", "origin/main"), res.stderr)


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
