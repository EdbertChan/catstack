#!/usr/bin/env python3
"""Tests for git_path_churn clustering and session pairing."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import git_path_churn as gpc  # noqa: E402


def _git(repo: str, *args: str, env: dict | None = None) -> None:
    base_env = os.environ.copy()
    base_env.update(
        {
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        }
    )
    if env:
        base_env.update(env)
    subprocess.run(
        ["git", "-C", repo, *args],
        check=True,
        capture_output=True,
        text=True,
        env=base_env,
    )


def _init_repo(tmp: str) -> str:
    repo = os.path.join(tmp, "repo")
    os.makedirs(repo)
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    return repo


def _commit_at(repo: str, path: str, content: str, subject: str, when: datetime) -> None:
    abs_path = os.path.join(repo, path)
    os.makedirs(os.path.dirname(abs_path) or repo, exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as handle:
        handle.write(content)
    _git(repo, "add", path)
    stamp = when.strftime("%Y-%m-%dT%H:%M:%S")
    env = {
        "GIT_AUTHOR_DATE": stamp,
        "GIT_COMMITTER_DATE": stamp,
    }
    _git(repo, "commit", "-m", subject, env=env)


class TestClusterPathChurn(unittest.TestCase):
    def test_three_commits_same_path_cluster(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _init_repo(tmp)
            t0 = datetime.now(timezone.utc) - timedelta(hours=2)
            for i in range(3):
                _commit_at(
                    repo,
                    "workers/foo.py",
                    f"v{i}\n",
                    f"patch workers {i}",
                    t0 + timedelta(minutes=10 * i),
                )
            events = gpc.events_from_git(repo, since_hours=24)
            kinds = [e["kind"] for e in events]
            self.assertIn("execution_rewritten", kinds)
            self.assertIn("execution_started", kinds)

    def test_two_commits_not_enough(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _init_repo(tmp)
            t0 = datetime.now(timezone.utc) - timedelta(hours=1)
            for i in range(2):
                _commit_at(
                    repo,
                    "workers/foo.py",
                    f"v{i}\n",
                    f"patch {i}",
                    t0 + timedelta(minutes=5 * i),
                )
            events = gpc.events_from_git(repo, since_hours=24)
            self.assertEqual(events, [])


class TestSessionGitPair(unittest.TestCase):
    def test_pair_emits_rewrite_on_churn(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _init_repo(tmp)
            t0 = datetime.now(timezone.utc) - timedelta(hours=1)
            for i in range(3):
                _commit_at(
                    repo,
                    "src/feature.py",
                    f"x{i}\n",
                    f"rewrite feature {i}",
                    t0 + timedelta(minutes=5 * i),
                )
            mtime = (t0 + timedelta(minutes=20)).timestamp()
            events = gpc.pair_session_to_commits(
                repo,
                session_mtime=mtime,
                path_hints=["src/feature.py"],
                execution_id="sess123",
                already_thrashed=False,
            )
            self.assertTrue(any(e["kind"] == "execution_rewritten" for e in events))
            self.assertTrue(all(e.get("execution_id") == "sess123" or e.get("incident_id") == "sess123" for e in events))

    def test_thrash_plus_two_commits_rewrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _init_repo(tmp)
            t0 = datetime.now(timezone.utc) - timedelta(hours=1)
            for i in range(2):
                _commit_at(
                    repo,
                    "src/a.py",
                    f"y{i}\n",
                    f"fix forward {i}",
                    t0 + timedelta(minutes=5 * i),
                )
            mtime = (t0 + timedelta(minutes=10)).timestamp()
            events = gpc.pair_session_to_commits(
                repo,
                session_mtime=mtime,
                path_hints=["src/a.py"],
                execution_id="thrash1",
                already_thrashed=True,
            )
            self.assertTrue(any(e["kind"] == "execution_rewritten" for e in events))


if __name__ == "__main__":
    unittest.main()
