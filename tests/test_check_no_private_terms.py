#!/usr/bin/env python3
"""Positive, negative, and unchecked tests for scripts/ci/check_no_private_terms.py."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "ci" / "check_no_private_terms.py"
sys.path.insert(0, str(REPO / "scripts" / "test"))
from git_test_repo import init_repo  # noqa: E402

TERM = "widgetcorp"
OTHER_TERM = "acme-internal.example"
ALLOWED_EMAIL = "dev@users.noreply.github.com"
WORK_EMAIL = "dev@acme-mail.example"


class Fixture:
    def __init__(self, root: Path):
        self.home = root / "home"
        self.home.mkdir()
        self.repo = root / "repo"
        self.environ = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "CATSTACK_"))}
        self.environ.update(
            HOME=str(self.home),
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_NOSYSTEM="1",
        )
        self.identity(ALLOWED_EMAIL)
        init_repo(self.repo, "-b", "main", env=self.environ)
        self.write("README.md", f"hello\nthis base line names {TERM} and is already published\n")
        self.commit("base")
        self.base = self.resolve("HEAD")

    def identity(self, email: str) -> None:
        for role in ("AUTHOR", "COMMITTER"):
            self.environ[f"GIT_{role}_NAME"] = "Dev"
            self.environ[f"GIT_{role}_EMAIL"] = email

    def denylist(self, *terms: str) -> Path:
        path = self.home / ".config" / "catstack" / "private-terms"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# private denylist\n\n" + "".join(f"{t}\n" for t in terms), encoding="utf-8")
        return path

    def write(self, relative_path: str, text: str) -> None:
        path = self.repo / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.repo), *args],
            capture_output=True, text=True, env=self.environ, check=True,
        ).stdout

    def commit(self, message: str) -> None:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def resolve(self, ref: str) -> str:
        return self.git("rev-parse", ref).strip()

    def run_scan(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=self.repo, capture_output=True, text=True, env=self.environ,
        )

    def scan(self) -> subprocess.CompletedProcess:
        return self.run_scan("--base", self.base)


class PrivateTermsScan(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.fixture = Fixture(Path(tmp.name))

    def assertTermsHidden(self, result: subprocess.CompletedProcess) -> None:
        for text in (TERM, OTHER_TERM, WORK_EMAIL):
            self.assertNotIn(text.casefold(), (result.stdout + result.stderr).casefold())

    def test_term_in_an_added_line_fires(self):
        self.fixture.denylist(OTHER_TERM, TERM)
        self.fixture.write("scripts/run.sh", "echo one\nssh build.WidgetCorp.lan\n")
        self.fixture.commit("add runner")
        result = self.fixture.scan()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("added scripts/run.sh:2: matched term #2", result.stdout)
        self.assertTermsHidden(result)

    def test_term_in_a_new_file_path_fires(self):
        self.fixture.denylist(TERM)
        self.fixture.write(f"notes/{TERM}-setup.txt", "nothing private inside\n")
        self.fixture.commit("add notes")
        result = self.fixture.scan()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("path notes/", result.stdout)
        self.assertIn(": matched term #1", result.stdout)

    def test_term_in_a_commit_message_fires(self):
        self.fixture.denylist(TERM)
        self.fixture.write("a.txt", "plain\n")
        self.fixture.commit(f"fix the {TERM.upper()} nightly")
        sha = self.fixture.resolve("HEAD")[:12]
        result = self.fixture.scan()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(f"message {sha}: matched term #1", result.stdout)
        self.assertTermsHidden(result)

    def test_author_email_off_the_allowed_list_fires(self):
        self.fixture.denylist(TERM)
        self.fixture.identity(WORK_EMAIL)
        self.fixture.write("a.txt", "plain\n")
        self.fixture.commit("plain change")
        sha = self.fixture.resolve("HEAD")[:12]
        result = self.fixture.scan()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(f"author {sha}: email is not on the allowed list", result.stdout)
        self.assertIn(f"committer {sha}: email is not on the allowed list", result.stdout)
        self.assertTermsHidden(result)

    def test_allowed_emails_file_admits_an_extra_address(self):
        self.fixture.denylist(TERM)
        allowed = self.fixture.home / ".config" / "catstack" / "allowed-emails"
        allowed.write_text("# extra\n*@acme-mail.example\n", encoding="utf-8")
        self.fixture.identity(WORK_EMAIL)
        self.fixture.write("a.txt", "plain\n")
        self.fixture.commit("plain change")
        result = self.fixture.scan()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_clean_range_exits_zero(self):
        self.fixture.denylist(TERM, OTHER_TERM)
        self.fixture.write("a.txt", "a widget corp, spelled apart, is not a match\n")
        self.fixture.commit("add a")
        result = self.fixture.scan()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ok      no private terms", result.stdout)
        self.assertIn("2 terms from", result.stdout)

    def test_term_only_in_a_removed_line_stays_silent(self):
        self.fixture.denylist(TERM)
        self.fixture.write("README.md", "hello\n")
        self.fixture.commit("drop the old line")
        result = self.fixture.scan()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTermsHidden(result)

    def test_environment_denylist_wins_over_the_file(self):
        self.fixture.denylist("nothing-matches-this")
        self.fixture.environ["CATSTACK_PRIVATE_TERMS"] = f"# from a secret\n{TERM}\n"
        self.fixture.write("a.txt", f"{TERM}\n")
        self.fixture.commit("add a")
        result = self.fixture.scan()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("added a.txt:1: matched term #1", result.stdout)
        self.assertTermsHidden(result)

    def test_no_denylist_is_unchecked_never_clean(self):
        self.fixture.write("a.txt", "plain\n")
        self.fixture.commit("add a")
        result = self.fixture.scan()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("unchecked  no denylist", result.stderr)
        self.assertIn("private-terms", result.stderr)
        self.assertNotIn("ok ", result.stdout)

    def test_denylist_file_variable_pointing_nowhere_is_unchecked(self):
        missing = self.fixture.home / "missing-terms"
        self.fixture.environ["CATSTACK_PRIVATE_TERMS_FILE"] = str(missing)
        result = self.fixture.scan()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn(str(missing), result.stderr)
        self.assertIn("CATSTACK_PRIVATE_TERMS_FILE points at it", result.stderr)

    def test_denylist_of_only_comments_is_unchecked(self):
        path = self.fixture.denylist()
        result = self.fixture.scan()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn(f"denylist {path} holds no terms", result.stderr)

    def test_unresolvable_base_is_unchecked(self):
        self.fixture.denylist(TERM)
        result = self.fixture.run_scan("--base", "no-such-ref")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("unchecked  git rev-parse", result.stderr)

    def test_from_root_scans_base_history_too(self):
        self.fixture.denylist(TERM)
        result = self.fixture.run_scan("--from-root")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("added README.md:2: matched term #1", result.stdout)
        self.assertTermsHidden(result)


if __name__ == "__main__":
    unittest.main()
