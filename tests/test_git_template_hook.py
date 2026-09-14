#!/usr/bin/env python3
"""Tests for scripts/install-git-template.sh and scripts/git-hooks/template-pre-push.

Every case points HOME, XDG_CONFIG_HOME and GIT_CONFIG_GLOBAL into a temp
dir, so the real global git config is never read or written. Push cases run
the installer, make a fresh clone that picks up the template hook through
init.templateDir, point origin at a GitHub URL that insteadOf rewrites to a
local bare remote, and push a real branch through the copied hook.
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
from git_test_repo import disable_background_maintenance, init_repo  # noqa: E402

PREFLIGHT = "engine/skills/make-pr/scripts/preflight.py"
UNIT_RULES = "drafter.config.json"
TRACKED_HOOK = "scripts/git-hooks/pre-push"
TEMPLATE_HOOK = "scripts/git-hooks/template-pre-push"
INSTALLER = REPO / "scripts/install-git-template.sh"
CATSTACK_URL = "https://github.com/EdbertChan/catstack.git"
OTHER_URL = "https://github.com/example/other.git"
UNCHECKED_LINE = (
    "pre-push: UNCHECKED: origin/main has no scripts/git-hooks/pre-push; "
    "run git fetch origin main, or push with --no-verify to bypass"
)
FOREIGN_HOOK = b"#!/bin/sh\necho someone else's template hook\nexit 0\n"
FAKE_GH_OPEN_PR = "#!/bin/sh\necho main\n"
MIXED = ("engine/hooks/x.py", "product/skills/y/run.py")


class Sandbox:
    def __init__(self, root: Path):
        self.root = root
        self.home = root / "home"
        self.xdg = root / "xdg"
        self.gitconfig = root / "gitconfig"
        self.hook_tmp = root / "hook-tmp"
        bin_dir = root / "bin"
        for d in (self.home, self.xdg, self.hook_tmp, bin_dir):
            d.mkdir()
        fake_gh = bin_dir / "gh"
        fake_gh.write_text(FAKE_GH_OPEN_PR, encoding="utf-8")
        fake_gh.chmod(0o755)
        self.template_dir = self.xdg / "catstack/git-template"
        self.template_hook = self.template_dir / "hooks/pre-push"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(
            HOME=str(self.home),
            XDG_CONFIG_HOME=str(self.xdg),
            GIT_CONFIG_GLOBAL=str(self.gitconfig),
            GIT_CONFIG_NOSYSTEM="1",
            GIT_AUTHOR_NAME="T",
            GIT_AUTHOR_EMAIL="t@example.invalid",
            GIT_COMMITTER_NAME="T",
            GIT_COMMITTER_EMAIL="t@example.invalid",
            TMPDIR=str(self.hook_tmp),
            PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        )
        self.remote = root / "remote.git"
        self.source = root / "source"
        self.clone = root / "clone"

    def run(self, *args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            list(args), cwd=cwd, capture_output=True, text=True, env=self.env, check=check,
        )

    def git(self, repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return self.run("git", "-C", str(repo), *args, check=check)

    def global_template_dir(self) -> str:
        return self.run("git", "config", "--global", "--get", "init.templateDir", check=False).stdout.strip()

    def install(self) -> subprocess.CompletedProcess:
        return self.run("bash", str(INSTALLER), check=False)

    def build_remote(self, files: tuple[str, ...]) -> None:
        seed = self.root / "seed"
        init_repo(self.remote, "--bare", "-b", "main", env=self.env)
        init_repo(seed, "-b", "main", env=self.env)
        for rel in files:
            dest = seed / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / rel, dest)
        self.git(seed, "add", "-A")
        self.git(seed, "commit", "-q", "-m", "main")
        self.git(seed, "push", "-q", str(self.remote), "main")

    def fresh_clone(self, url: str) -> None:
        self.run("git", "clone", "-q", str(self.remote), str(self.source))
        disable_background_maintenance(self.source, env=self.env)
        self.run("git", "clone", "-q", "--local", "--no-checkout", str(self.source), str(self.clone))
        disable_background_maintenance(self.clone, env=self.env)
        self.git(self.clone, "remote", "set-url", "origin", url)
        self.git(self.clone, "config", f"url.{self.remote}.insteadOf", url)
        self.git(self.clone, "fetch", "-q", "origin")
        self.git(self.clone, "checkout", "-q", "main")

    def clone_hook(self) -> Path:
        return self.clone / ".git/hooks/pre-push"

    def branch(self, name: str, paths: tuple[str, ...]) -> None:
        self.git(self.clone, "checkout", "-q", "-b", name, "main")
        for rel in paths:
            dest = self.clone / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(f"{rel}\n", encoding="utf-8")
        self.git(self.clone, "add", "-A")
        self.git(self.clone, "commit", "-q", "-m", name)

    def push(self, branch: str) -> subprocess.CompletedProcess:
        return self.git(self.clone, "push", "origin", branch, check=False)

    def remote_has(self, branch: str) -> bool:
        res = self.git(self.remote, "rev-parse", "--verify", "-q", f"refs/heads/{branch}", check=False)
        return res.returncode == 0


class TestInstaller(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.box = Sandbox(Path(self._tmp.name))

    def test_unset_template_dir_is_set_and_hook_written(self):
        box = self.box
        self.assertEqual(box.global_template_dir(), "")
        res = box.install()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(box.global_template_dir(), str(box.template_dir))
        self.assertEqual(box.template_hook.read_bytes(), (REPO / TEMPLATE_HOOK).read_bytes())
        self.assertTrue(os.access(box.template_hook, os.X_OK))
        again = box.install()
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertEqual(box.global_template_dir(), str(box.template_dir))

    def test_template_dir_set_elsewhere_is_left_unchanged(self):
        box = self.box
        other = box.root / "other-template"
        (other / "hooks").mkdir(parents=True)
        (other / "hooks/pre-push").write_bytes(FOREIGN_HOOK)
        box.run("git", "config", "--global", "init.templateDir", str(other))
        config_before = box.gitconfig.read_bytes()
        res = box.install()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn(f"init.templateDir is already {other}; leaving it alone", res.stdout)
        self.assertEqual(box.global_template_dir(), str(other))
        self.assertEqual(box.gitconfig.read_bytes(), config_before)
        self.assertEqual(sorted(p.name for p in other.rglob("*")), ["hooks", "pre-push"])
        self.assertEqual((other / "hooks/pre-push").read_bytes(), FOREIGN_HOOK)
        self.assertFalse(box.template_dir.exists())

    def test_foreign_template_pre_push_is_left_unchanged(self):
        box = self.box
        box.template_hook.parent.mkdir(parents=True)
        box.template_hook.write_bytes(FOREIGN_HOOK)
        res = box.install()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn(f"{box.template_hook} was not written by catstack; leaving it alone", res.stdout)
        self.assertEqual(box.template_hook.read_bytes(), FOREIGN_HOOK)
        self.assertEqual(box.global_template_dir(), "")


class TestTemplateHookInFreshClone(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.box = Sandbox(Path(self._tmp.name))
        res = self.box.install()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def clone_and_branch(self, remote_files: tuple[str, ...], url: str) -> Sandbox:
        box = self.box
        box.build_remote(remote_files)
        box.fresh_clone(url)
        self.assertEqual(box.clone_hook().read_bytes(), (REPO / TEMPLATE_HOOK).read_bytes())
        box.branch("mixed", MIXED)
        return box

    def test_catstack_clone_refuses_mixed_push(self):
        box = self.clone_and_branch((UNIT_RULES, PREFLIGHT, TRACKED_HOOK, TEMPLATE_HOOK), CATSTACK_URL)
        res = box.push("mixed")
        self.assertNotEqual(res.returncode, 0, res.stderr)
        self.assertIn("more than one review unit", res.stderr)
        self.assertIn("pre-push: refusing refs/heads/mixed: make one branch per review unit", res.stderr)
        self.assertFalse(box.remote_has("mixed"))
        self.assertEqual(os.listdir(box.hook_tmp), [])

    def test_other_repo_clone_pushes_mixed_branch(self):
        box = self.clone_and_branch((UNIT_RULES, PREFLIGHT, TRACKED_HOOK, TEMPLATE_HOOK), OTHER_URL)
        res = box.push("mixed")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("review unit", res.stderr)
        self.assertTrue(box.remote_has("mixed"))
        self.assertEqual(os.listdir(box.hook_tmp), [])

    def test_catstack_clone_without_tracked_hook_is_refused_as_unchecked(self):
        box = self.clone_and_branch((UNIT_RULES, PREFLIGHT, TEMPLATE_HOOK), CATSTACK_URL)
        res = box.push("mixed")
        self.assertNotEqual(res.returncode, 0, res.stderr)
        self.assertIn(UNCHECKED_LINE, res.stderr)
        self.assertFalse(box.remote_has("mixed"))


if __name__ == "__main__":
    unittest.main()
