#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "check_branch_not_superseded.py"
sys.path.insert(0, str(REPO / "scripts"))

import check_branch_not_superseded as gate  # noqa: E402
from git_test_repo import init_repo  # noqa: E402

HERMETIC_ENV = dict(
    os.environ,
    GIT_CONFIG_GLOBAL=os.devnull,
    GIT_CONFIG_NOSYSTEM="1",
    GIT_AUTHOR_NAME="Fixture",
    GIT_AUTHOR_EMAIL="fixture@example.com",
    GIT_COMMITTER_NAME="Fixture",
    GIT_COMMITTER_EMAIL="fixture@example.com",
)
EXPECTED_EXIT = {"LIVE": 0, "UNCHECKED": 2, "SUPERSEDED": 3}


def lines(tag: str, count: int = 30) -> str:
    return "".join(f"{tag} line {i}\n" for i in range(count))


class Fixture:
    def __init__(self, root: Path):
        self.root = root
        init_repo(root, "-b", "main", env=HERMETIC_ENV)

    def git(self, *args: str) -> str:
        return subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True,
                              text=True, env=HERMETIC_ENV).stdout.strip()

    def write(self, path: str, text: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def commit(self, message: str, files: dict[str, str | None]) -> str:
        for path, text in files.items():
            if text is None:
                self.git("rm", "-q", path)
            else:
                self.write(path, text)
                self.git("add", path)
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def seed(self, count: int = 10) -> None:
        self.commit("seed", {f"docs/f{i}.md": lines(f"f{i}") for i in range(count)})

    def base_moves_on(self, count: int = 10) -> None:
        self.git("checkout", "-q", "main")
        for i in range(1, count):
            self.commit(f"grow f{i}", {f"docs/f{i}.md": lines(f"f{i}") + lines(f"grow{i}", 20)})
        self.commit("add g", {"docs/g.md": lines("g", 60)})

    def run(self, ref: str, *extra: str) -> tuple[int, dict]:
        proc = subprocess.run([sys.executable, str(SCRIPT), ref, "--base", "main", "--repo", str(self.root),
                               "--json", *extra], capture_output=True, text=True, env=HERMETIC_ENV)
        return proc.returncode, json.loads(proc.stdout)


class FixtureCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Fixture(Path(self._tmp.name) / "repo")
        self.repo.seed()

    def assertVerdict(self, ref: str, verdict: str, *extra: str) -> dict:
        code, result = self.repo.run(ref, *extra)
        self.assertEqual(result["verdict"], verdict, result)
        self.assertEqual(code, EXPECTED_EXIT[verdict], result)
        return result


class TestSuperseded(FixtureCase):
    def test_branch_whose_commit_was_cherry_picked_then_base_moved_on(self):
        self.repo.git("checkout", "-q", "-b", "topic")
        landed = self.repo.commit("topic change", {"docs/f0.md": lines("f0") + "topic line\n"})
        self.repo.git("checkout", "-q", "main")
        self.repo.commit("unrelated", {"docs/h.md": "h\n"})
        self.repo.git("cherry-pick", landed)
        self.repo.base_moves_on()
        listed = self.repo.git("diff", "--name-only", "main..topic").splitlines()
        self.assertGreaterEqual(len(listed), 10)
        result = self.assertVerdict("topic", gate.SUPERSEDED)
        n = result["numbers"]
        self.assertEqual((n["ahead"], n["unique_commits"]), (1, 0))
        self.assertEqual(n["behind"], 12)
        self.assertEqual(n["files_differ"], len(listed))
        self.assertEqual((n["files_behind"], n["files_ahead"]), (len(listed), 0))
        self.assertGreater(n["deletions"], n["additions"])
        self.assertIn("git cherry shows no '+'", result["reason"])

    def test_branch_the_base_already_contains(self):
        self.repo.git("checkout", "-q", "-b", "topic")
        self.repo.commit("topic change", {"docs/f0.md": lines("f0") + "topic line\n"})
        self.repo.git("checkout", "-q", "main")
        self.repo.git("merge", "-q", "--no-ff", "-m", "merge topic", "topic")
        self.repo.base_moves_on()
        n = self.assertVerdict("topic", gate.SUPERSEDED)["numbers"]
        self.assertEqual((n["ahead"], n["unique_commits"]), (0, 0))

    def test_squash_landed_then_edited_on_base(self):
        self.repo.git("checkout", "-q", "-b", "topic")
        self.repo.commit("topic one", {"docs/f0.md": lines("f0") + "topic one\n"})
        self.repo.commit("topic two", {"docs/f0.md": lines("f0") + "topic one\ntopic two\n"})
        self.repo.git("checkout", "-q", "main")
        self.repo.git("merge", "-q", "--squash", "topic")
        self.repo.git("commit", "-q", "-m", "squash topic")
        self.repo.commit("reword", {"docs/f0.md": lines("f0") + "topic one, reworded\ntopic two\n"})
        self.repo.base_moves_on()
        result = self.assertVerdict("topic", gate.SUPERSEDED)
        n = result["numbers"]
        self.assertEqual(n["unique_commits"], 2)
        self.assertEqual(n["files_ahead"], 0)
        self.assertEqual(n["added_lines_missing_from_base"], 1)
        self.assertIn("every file that differs is behind the base", result["reason"])

    def test_squash_landed_beside_a_concurrent_edit_to_the_same_file(self):
        self.repo.git("checkout", "-q", "-b", "topic")
        self.repo.commit("topic one", {"docs/f0.md": "topic head\n" + lines("f0")})
        self.repo.commit("topic two", {"docs/f0.md": "topic head\ntopic second\n" + lines("f0")})
        self.repo.git("checkout", "-q", "main")
        self.repo.commit("tail edit", {"docs/f0.md": lines("f0") + "base tail\n"})
        self.repo.commit("squash topic", {"docs/f0.md": "topic head\ntopic second\n" + lines("f0") + "base tail\n"})
        self.repo.base_moves_on()
        result = self.assertVerdict("topic", gate.SUPERSEDED)
        n = result["numbers"]
        self.assertEqual(n["unique_commits"], 2)
        self.assertGreater(n["files_ahead"], 0)
        self.assertEqual((n["added_lines_missing_from_base"], n["removed_lines_still_on_base"]), (0, 0))
        self.assertIn("own change is already on the base", result["reason"])


class TestLive(FixtureCase):
    def test_branch_with_a_new_commit_on_an_unmoved_base(self):
        self.repo.git("checkout", "-q", "-b", "topic")
        self.repo.commit("topic change", {"docs/new.md": lines("new", 12)})
        n = self.assertVerdict("topic", gate.LIVE)["numbers"]
        self.assertEqual((n["ahead"], n["behind"], n["unique_commits"]), (1, 0, 1))
        self.assertEqual((n["additions"], n["deletions"]), (12, 0))
        self.assertEqual((n["files_differ"], n["files_ahead"]), (1, 1))

    def test_branch_both_ahead_and_far_behind_is_live(self):
        self.repo.git("checkout", "-q", "-b", "topic")
        self.repo.commit("topic change", {"docs/new.md": lines("new", 3)})
        self.repo.base_moves_on()
        n = self.assertVerdict("topic", gate.LIVE)["numbers"]
        self.assertEqual((n["ahead"], n["behind"], n["unique_commits"]), (1, 10, 1))
        self.assertGreater(n["deletions"], n["additions"])
        self.assertEqual(n["files_ahead"], 1)
        self.assertEqual(n["added_lines_missing_from_base"], 3)

    def test_branch_that_only_deletes_while_far_behind_is_live(self):
        self.repo.git("checkout", "-q", "-b", "topic")
        self.repo.commit("drop f0", {"docs/f0.md": None})
        self.repo.base_moves_on()
        n = self.assertVerdict("topic", gate.LIVE)["numbers"]
        self.assertEqual(n["additions"], 0)
        self.assertEqual(n["added_lines_missing_from_base"], 0)
        self.assertEqual(n["removed_lines_still_on_base"], 30)
        self.assertEqual(n["files_ahead"], 1)

    def test_mode_only_change_while_far_behind_is_live(self):
        self.repo.git("checkout", "-q", "-b", "topic")
        (self.repo.root / "docs/f0.md").chmod(0o755)
        self.repo.git("add", "docs/f0.md")
        self.repo.git("commit", "-q", "-m", "make f0 executable")
        self.repo.base_moves_on()
        n = self.assertVerdict("topic", gate.LIVE)["numbers"]
        self.assertEqual(n["files_ahead"], 1)
        self.assertEqual(n["unreadable_branch_files"], 1)


class TestUnchecked(FixtureCase):
    def assertUnchecked(self, ref: str, reason: str, *extra: str) -> None:
        result = self.assertVerdict(ref, gate.UNCHECKED, *extra)
        self.assertIn(reason, result["reason"])
        self.assertIsNone(result["numbers"])

    def test_unresolvable_ref(self):
        self.assertUnchecked("no-such-branch", "does not resolve")

    def test_unfetched_base(self):
        self.repo.git("checkout", "-q", "-b", "topic")
        self.repo.commit("topic change", {"docs/new.md": "x\n"})
        self.assertUnchecked("topic", "fetch it first", "--base", "origin/main")

    def test_no_shared_history(self):
        self.repo.git("checkout", "-q", "--orphan", "island")
        self.repo.git("rm", "-rqf", ".")
        self.repo.commit("island", {"island.md": "alone\n"})
        self.assertUnchecked("island", "share no history")

    def test_shallow_clone(self):
        self.repo.git("checkout", "-q", "-b", "topic")
        self.repo.commit("topic change", {"docs/new.md": "x\n"})
        shallow = Path(self._tmp.name) / "shallow"
        subprocess.run(["git", "clone", "-q", "--depth", "1", "--no-single-branch",
                        f"file://{self.repo.root}", str(shallow)], check=True, capture_output=True, env=HERMETIC_ENV)
        self.repo.root = shallow
        self.assertUnchecked("origin/topic", "shallow", "--base", "origin/main")

    def test_ref_that_looks_like_an_option(self):
        result = gate.evaluate(str(self.repo.root), "--output=/tmp/x", "main", "origin")
        self.assertEqual(result["verdict"], gate.UNCHECKED)
        self.assertIn("does not resolve", result["reason"])

    def test_unchecked_never_shares_an_exit_code(self):
        self.assertEqual(gate.EXIT_CODES, EXPECTED_EXIT)
        self.assertEqual(len(set(gate.EXIT_CODES.values())), 3)
        self.assertNotEqual(gate.EXIT_CODES[gate.UNCHECKED], gate.EXIT_CODES[gate.LIVE])
        self.assertNotEqual(gate.EXIT_CODES[gate.UNCHECKED], 1)
        self.assertNotEqual(gate.EXIT_CODES[gate.SUPERSEDED], 1)

    def test_text_report_says_numbers_were_not_computed(self):
        proc = subprocess.run([sys.executable, str(SCRIPT), "no-such-branch", "--base", "main",
                               "--repo", str(self.repo.root)], capture_output=True, text=True, env=HERMETIC_ENV)
        self.assertEqual(proc.returncode, EXPECTED_EXIT[gate.UNCHECKED])
        self.assertIn("UNCHECKED", proc.stdout)
        self.assertIn("not computed, so this is not a pass", proc.stdout)
        self.assertIn("UNCHECKED", proc.stderr)


class TestPullRefs(FixtureCase):
    def setUp(self):
        super().setUp()
        self.remote = Path(self._tmp.name) / "remote.git"
        init_repo(self.remote, "--bare", env=HERMETIC_ENV)
        self.repo.git("remote", "add", "origin", str(self.remote))
        self.repo.git("checkout", "-q", "-b", "topic")
        self.repo.commit("topic change", {"docs/new.md": lines("new", 4)})
        self.repo.git("push", "-q", "origin", "topic:refs/pull/7/head", "main:main")
        self.repo.git("checkout", "-q", "main")
        self.repo.git("branch", "-D", "topic")

    def test_hash_number_fetches_the_pull_head(self):
        for ref in ("#7", "pull/7", "refs/pull/7/head"):
            with self.subTest(ref=ref):
                n = self.assertVerdict(ref, gate.LIVE)["numbers"]
                self.assertEqual((n["ahead"], n["unique_commits"], n["additions"]), (1, 1, 4))

    def test_missing_pull_head_is_unchecked(self):
        result = self.assertVerdict("#8", gate.UNCHECKED)
        self.assertIn("could not fetch refs/pull/8/head", result["reason"])


class TestReportFormat(FixtureCase):
    def test_text_report_names_every_number(self):
        self.repo.git("checkout", "-q", "-b", "topic")
        self.repo.commit("topic change", {"docs/new.md": "x\n"})
        proc = subprocess.run([sys.executable, str(SCRIPT), "topic", "--base", "main", "--repo", str(self.repo.root)],
                              capture_output=True, text=True, env=HERMETIC_ENV)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for label in ("commits ahead: 1 (1 not on the base)", "commits behind: 0", "net additions: 1",
                      "net deletions: 0", "files differ: 1 (0 behind the base, 1 ahead of it)"):
            self.assertIn(label, proc.stdout)


class TestExemplars(unittest.TestCase):
    def test_catch_exemplars_are_superseded(self):
        for ex in gate.PROMISED_CATCH:
            with self.subTest(ex=ex):
                self.assertTrue(gate.flags_exemplar(ex))

    def test_allow_exemplars_are_live(self):
        for ex in gate.PROMISED_ALLOW:
            with self.subTest(ex=ex):
                self.assertFalse(gate.flags_exemplar(ex))
                self.assertEqual(gate.classify(gate.exemplar_evidence(ex))[0], gate.LIVE)


if __name__ == "__main__":
    unittest.main()
