#!/usr/bin/env python3
"""Positive + negative tests for scripts/git_test_repo.py.

The negative control is the point: a plain `git init` repo still lets
`git commit` spawn auto maintenance, and on git 2.55 that process is
detached and outlives the commit, racing TemporaryDirectory cleanup.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from git_test_repo import init_repo  # noqa: E402

GIT_INIT_CALL_RES = (
    re.compile(r"""["']git["']\s*,\s*["']init["']"""),
    re.compile(r"""\bgit\s+init\b"""),
    re.compile(r"""_git\([^,]+,\s*["']init["']"""),
)
HELPER_OWNED = {
    "scripts/git_test_repo.py",
    "scripts/repro_tempdir_git_cleanup_race.py",
    "tests/test_git_test_repo.py",
}


def _config(root, key: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "config", "--get", key],
        capture_output=True, text=True,
    ).stdout.strip()


def _commit_trace(root) -> str:
    for key, value in (("user.email", "t@example.invalid"), ("user.name", "T")):
        subprocess.run(["git", "-C", str(root), "config", key, value], check=True, capture_output=True)
    (Path(root) / "f.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, capture_output=True)
    return subprocess.run(
        ["git", "-C", str(root), "commit", "-q", "-m", "one"],
        capture_output=True, text=True, env={"GIT_TRACE": "1", "PATH": "/usr/bin:/bin:/usr/local/bin"},
    ).stderr


class TestInitRepo(unittest.TestCase):
    def test_repo_config_turns_off_gc_and_maintenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_repo(tmp, "-b", "main")
            self.assertEqual(_config(tmp, "gc.auto"), "0")
            self.assertEqual(_config(tmp, "maintenance.auto"), "false")

    def test_commit_spawns_no_background_maintenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_repo(tmp, "-b", "main")
            self.assertNotIn("maintenance run --auto", _commit_trace(tmp))

    def test_plain_init_repo_still_spawns_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q", "-b", "main", tmp], check=True, capture_output=True)
            self.assertIn("maintenance run --auto", _commit_trace(tmp))

    def test_settings_survive_a_replacement_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_repo(tmp, "-b", "main", env={"PATH": "/usr/bin:/bin:/usr/local/bin"})
            self.assertEqual(_config(tmp, "gc.auto"), "0")


class TestNoDirectGitInitInTests(unittest.TestCase):
    def test_every_test_file_creates_repos_through_the_helper(self):
        offenders = []
        for path in sorted(REPO.rglob("test*.py")):
            rel = path.relative_to(REPO).as_posix()
            if rel.startswith((".worktrees/", "node_modules/")) or rel in HELPER_OWNED:
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if any(pattern.search(line) for pattern in GIT_INIT_CALL_RES):
                    offenders.append(f"{rel}:{number}: {line.strip()}")
        self.assertEqual(offenders, [], "use scripts/git_test_repo.init_repo instead:\n" + "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()
