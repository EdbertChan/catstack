#!/usr/bin/env python3
"""Focused tests for repository-local handoff artifact scrubbing."""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "scrub-handoff-artifacts.sh"


class TestHandoffScrub(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary_directory.name)
        subprocess.run(["git", "init", "--quiet"], cwd=self.repo, check=True)
        subprocess.run(
            ["git", "config", "user.email", "handoff-scrub@example.invalid"],
            cwd=self.repo,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Handoff Scrub Test"],
            cwd=self.repo,
            check=True,
        )
        script_directory = self.repo / "scripts"
        script_directory.mkdir()
        self.script = script_directory / SCRIPT.name
        shutil.copy2(SCRIPT, self.script)
        self.script.chmod(self.script.stat().st_mode | stat.S_IXUSR)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def write(self, relative_path: str, contents: str = "artifact\n") -> Path:
        path = self.repo / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
        return path

    def run_scrub(self, *, env: dict[str, str] | None = None):
        return subprocess.run(
            ["bash", str(self.script)],
            cwd=self.repo.parent,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )

    def test_removes_only_handoff_artifacts_and_preserves_protected_paths(self):
        removed = [
            self.write("candidates.json"),
            self.write("work/research-topic.json"),
            self.write("deep/one/two/three/four/lens-security.json"),
            self.write("plans/invoker-handoff.md"),
            self.write("plans/invoker-handoff.yaml"),
        ]
        preserved = [
            self.write("keep.json"),
            self.write("research-topic.txt"),
            self.write(".git/research-private.json"),
            self.write("node_modules/research-topic.json"),
            self.write("scripts/candidates.json"),
            self.write("packages/lens-security.json"),
            self.write("nested/node_modules/candidates.json"),
            self.write("nested/scripts/research-topic.json"),
            self.write("nested/packages/lens-security.json"),
        ]

        with tempfile.TemporaryDirectory() as home_directory:
            home_artifact = Path(home_directory) / "candidates.json"
            home_artifact.write_text("home state\n", encoding="utf-8")
            env = os.environ.copy()
            env["HOME"] = home_directory

            result = self.run_scrub(env=env)

            self.assertTrue(home_artifact.exists())

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(all(not path.exists() for path in removed))
        self.assertTrue(all(path.exists() for path in preserved))

    def test_commits_tracked_handoff_deletions(self):
        tracked = self.write("handoff/research-42.json")
        kept = self.write("notes.txt", "keep\n")
        unrelated_deletion = self.write("unrelated.txt", "leave unstaged\n")
        subprocess.run(["git", "add", "--all"], cwd=self.repo, check=True)
        subprocess.run(
            ["git", "commit", "--quiet", "-m", "test fixture"],
            cwd=self.repo,
            check=True,
        )
        unrelated_deletion.unlink()

        result = self.run_scrub()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(tracked.exists())
        self.assertTrue(kept.exists())
        subject = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            cwd=self.repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        self.assertEqual(
            subject,
            "chore: scrub inter-task handoff artifacts before merge\n",
        )
        committed_paths = subprocess.run(
            ["git", "show", "--pretty=format:", "--name-only", "HEAD"],
            cwd=self.repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        self.assertEqual(committed_paths, ["handoff/research-42.json"])
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=self.repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        self.assertEqual(status, " D unrelated.txt\n")

    def test_does_not_commit_unrelated_deletions_under_a_research_or_lens_named_directory(self):
        tracked = self.write("research-notes/unrelated.json")
        also_tracked = self.write("lens-project/other.json")
        subprocess.run(["git", "add", "--all"], cwd=self.repo, check=True)
        subprocess.run(
            ["git", "commit", "--quiet", "-m", "test fixture"],
            cwd=self.repo,
            check=True,
        )
        tracked.unlink()
        also_tracked.unlink()

        result = self.run_scrub()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=self.repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        self.assertEqual(
            status,
            " D lens-project/other.json\n D research-notes/unrelated.json\n",
        )

    def test_fails_when_a_matching_file_remains(self):
        artifact = self.write("research-blocked.json")
        fake_bin = self.repo / "fake-bin"
        fake_bin.mkdir()
        fake_rm = fake_bin / "rm"
        fake_rm.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        fake_rm.chmod(fake_rm.stat().st_mode | stat.S_IXUSR)
        env = os.environ.copy()
        env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"

        result = self.run_scrub(env=env)

        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(artifact.exists())
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "handoff files remain in worktree\n")

    def test_prints_exact_success_line_for_clean_repository(self):
        result = self.run_scrub()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "scrub-handoff-artifacts-ok\n")
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
