#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import string
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "probe_branch_rebase.sh"
sys.path.insert(0, str(REPO / "scripts"))

from git_test_repo import init_repo  # noqa: E402

HERMETIC_ENV = dict(
    os.environ,
    GIT_CONFIG_GLOBAL=os.devnull,
    GIT_CONFIG_NOSYSTEM="1",
    GIT_AUTHOR_NAME="Fixture",
    GIT_AUTHOR_EMAIL="fixture@example.invalid",
    GIT_COMMITTER_NAME="Fixture",
    GIT_COMMITTER_EMAIL="fixture@example.invalid",
)


class Fixture:
    def __init__(self, root: Path):
        self.root = root
        init_repo(root, "-b", "main", env=HERMETIC_ENV)
        self.commit("seed", {"file.txt": "seed\n"})

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.root), *args],
            check=True,
            capture_output=True,
            text=True,
            env=HERMETIC_ENV,
        ).stdout.strip()

    def commit(self, message: str, files: dict[str, str]) -> None:
        for path, text in files.items():
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            self.git("add", path)
        self.git("commit", "-q", "-m", message)

    def run_probe(self, source_ref: str, base_ref: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(SCRIPT), source_ref, base_ref],
            cwd=self.root,
            capture_output=True,
            text=True,
            env=HERMETIC_ENV,
        )

    def scratch_path(self, source_ref: str, base_ref: str) -> Path:
        allowed = set(string.ascii_letters + string.digits + "._-")

        def safe(value: str) -> str:
            return "".join(ch if ch in allowed else "_" for ch in value)[:40]

        digest = subprocess.run(
            ["git", "-C", str(self.root), "hash-object", "--stdin"],
            input=f"{source_ref}\n{base_ref}\n",
            check=True,
            capture_output=True,
            text=True,
            env=HERMETIC_ENV,
        ).stdout.strip()[:12]
        scratch_root = Path(self.git("rev-parse", "--git-path", "rebase-probe-worktrees"))
        if not scratch_root.is_absolute():
            scratch_root = self.root / scratch_root
        return scratch_root / f"probe-{safe(source_ref)}-onto-{safe(base_ref)}-{digest}"

    def add_stale_probe_worktree(self, source_ref: str, base_ref: str) -> None:
        scratch = self.scratch_path(source_ref, base_ref)
        scratch.parent.mkdir(parents=True, exist_ok=True)
        self.git("worktree", "add", "--detach", str(scratch), source_ref)
        shutil.rmtree(scratch)


class ProbeBranchRebaseTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Fixture(Path(self._tmp.name) / "repo")

    def make_clean_rebase(self) -> None:
        self.repo.git("checkout", "-q", "-b", "topic")
        self.repo.commit("topic adds file", {"topic.txt": "topic\n"})
        self.repo.git("checkout", "-q", "main")
        self.repo.commit("base adds file", {"base.txt": "base\n"})

    def make_conflicting_rebase(self) -> None:
        self.repo.git("checkout", "-q", "-b", "topic")
        self.repo.commit("topic edits file", {"file.txt": "topic\n"})
        self.repo.git("checkout", "-q", "main")
        self.repo.commit("base edits file", {"file.txt": "base\n"})

    def test_clean_rebase_exits_ok(self):
        self.make_clean_rebase()

        result = self.repo.run_probe("topic", "main")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.repo.scratch_path("topic", "main").exists())

    def test_content_conflict_exits_fail(self):
        self.make_conflicting_rebase()

        result = self.repo.run_probe("topic", "main")

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("could not apply", result.stderr)
        self.assertFalse(self.repo.scratch_path("topic", "main").exists())

    def test_missing_registered_scratch_worktree_exits_unchecked(self):
        self.make_conflicting_rebase()
        self.repo.add_stale_probe_worktree("topic", "main")

        result = self.repo.run_probe("topic", "main")

        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn("missing but already registered worktree", result.stderr)
        self.assertIn("UNCHECKED: could not create scratch worktree", result.stderr)


if __name__ == "__main__":
    unittest.main()
