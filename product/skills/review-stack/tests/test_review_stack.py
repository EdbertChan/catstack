"""The three review-stack scripts on small temporary git repositories: slicing, rendering and the left-behind sweep."""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import build_review_stack  # noqa: E402
import left_behind_sweep  # noqa: E402
import stack_review_page  # noqa: E402


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=True).stdout


def make_repo(tmp):
    repo = os.path.join(tmp, "repo")
    os.makedirs(os.path.join(repo, "tests"))
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    Path(repo, "old.py").write_text("print('old')\n")
    Path(repo, "README.md").write_text("start\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "start")
    git(repo, "checkout", "-q", "-b", "end")
    os.makedirs(os.path.join(repo, "pkg", "model"))
    Path(repo, "pkg", "__init__.py").write_text("")
    Path(repo, "pkg", "model", "__init__.py").write_text("")
    Path(repo, "pkg", "model", "math.py").write_text("def add(a, b):\n    return a + b\n")
    Path(repo, "tests", "__init__.py").write_text("")
    Path(repo, "tests", "test_math.py").write_text(
        "import unittest\nfrom pkg.model.math import add\n\nclass T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(1, 2), 3)\n")
    Path(repo, "README.md").write_text("start\nmore\n")
    os.remove(os.path.join(repo, "old.py"))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "the package replaces the old script")
    return repo


class BuildReviewStack(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = make_repo(self.tmp)

    def slices(self, second_globs):
        path = os.path.join(self.tmp, "slices.json")
        json.dump([
            {"slug": "model", "title": "model/: pure code", "body": "The math.", "globs": ["pkg/*", "pkg/model/*", "tests/*"]},
            {"slug": "retire", "title": "Retire the old script", "globs": second_globs, "removals": ["*"]},
        ], open(path, "w"))
        return path

    def test_cuts_the_range_into_branches_whose_last_tree_equals_the_end(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = build_review_stack.main(self.repo, "main", "end", "review", self.slices(["README.md"]))
        text = out.getvalue()
        self.assertEqual(rc, 0, text)
        self.assertIn("tree difference between last slice and end: none (identical)", text)
        self.assertIn("Ran 1 test", text)
        self.assertEqual(git(self.repo, "rev-parse", "review/2-retire^{tree}"), git(self.repo, "rev-parse", "end^{tree}"))
        first = git(self.repo, "ls-tree", "-r", "--name-only", "review/1-model").split()
        self.assertIn("pkg/model/math.py", first)
        self.assertIn("old.py", first)
        self.assertNotIn("old.py", git(self.repo, "ls-tree", "-r", "--name-only", "review/2-retire").split())

    def test_fails_when_a_changed_path_is_claimed_by_no_slice(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = build_review_stack.main(self.repo, "main", "end", "review", self.slices(["docs/*"]))
        self.assertEqual(rc, 1)
        self.assertIn("unclaimed changed paths: ['README.md']", out.getvalue())


class StackReviewPage(unittest.TestCase):
    def test_renders_one_section_per_slice_with_the_claim_block_and_the_diff(self):
        tmp = tempfile.mkdtemp()
        repo = make_repo(tmp)
        meta = os.path.join(tmp, "meta.json")
        json.dump([{"label": "the package", "base": "main", "head": "end", "lane": "behavior", "claim": "A package replaces the script.",
                    "safety": "Tests cover the math."}], open(meta, "w"))
        out = os.path.join(tmp, "page.html")
        with contextlib.redirect_stdout(io.StringIO()):
            stack_review_page.main(repo, out, "--title=Round 9", f"--slices={meta}")
        page = Path(out).read_text()
        self.assertEqual(page.count("<section"), 1)
        self.assertIn("<title>Round 9</title>", page)
        self.assertIn("A package replaces the script.", page)
        self.assertIn("Safety invariant (proposed)", page)
        self.assertIn("pkg/model/math.py", page)
        self.assertIn("+def add(a, b):", page)
        self.assertIn("deleted file", page)
        self.assertNotIn("similarity index", page)


class LeftBehindSweep(unittest.TestCase):
    def test_flags_a_branch_with_a_real_patch_and_a_dirty_worktree_and_is_clean_otherwise(self):
        tmp = tempfile.mkdtemp()
        repo = make_repo(tmp)
        with contextlib.redirect_stdout(io.StringIO()):
            clean = left_behind_sweep.main([repo, "end"])
        self.assertEqual(clean, 0)
        git(repo, "checkout", "-q", "-b", "side", "main")
        Path(repo, "side.txt").write_text("x\n")
        git(repo, "add", "side.txt")
        git(repo, "commit", "-q", "-m", "a real change on a side branch")
        git(repo, "commit", "-q", "--allow-empty", "-m", "invoker: task marker")
        git(repo, "checkout", "-q", "end")
        wt = os.path.join(tmp, "wt")
        git(repo, "worktree", "add", "-q", wt, "main")
        Path(wt, "README.md").write_text("edited but not committed\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = left_behind_sweep.main([repo, "end"])
        text = out.getvalue()
        self.assertEqual(rc, 1)
        self.assertIn("side (last commit", text)
        self.assertIn("1 patches", text)
        self.assertNotIn("task marker", text)
        self.assertIn("dirty worktrees: 1", text)


class SkillProse(unittest.TestCase):
    """The standing rules of the comment loop and the pre-publish self-review are stated in the skill."""

    def setUp(self):
        self.prose = (Path(__file__).resolve().parents[1] / "SKILL.md").read_text()

    def test_names_a_rule_collision_and_the_base_first_option(self):
        self.assertIn("Name the collision in one line", self.prose)
        self.assertIn("land on the base first", self.prose)
        self.assertIn("stays in every status reply", self.prose)

    def test_runs_the_self_review_checklist_before_publishing(self):
        self.assertIn("## 2.5. Self-review the diff", self.prose)
        for item in ("Short or coined names", "Docstrings longer than one line", "Code nothing reads",
                     "Files outside the tool's own folder", "undoes a change an earlier slice made",
                     "Files the base already has that the stack modifies"):
            self.assertIn(item, self.prose)
        self.assertIn("self-review: 6/6 checked", self.prose)

    def test_acknowledges_fast_answers_with_evidence_and_closes_per_round(self):
        self.assertIn("Acknowledge each new thread with one sentence", self.prose)
        self.assertIn("answered with a pasted command output", self.prose)
        self.assertIn("in the same turn as the republish", self.prose)
        self.assertIn("Answer the round when it is done, not once per wake", self.prose)

    def test_treats_an_auto_reply_as_a_draft_that_the_session_checks(self):
        self.assertIn("A reply the agent did not write is a draft, not an answer", self.prose)
        self.assertIn("held, was corrected,\nor was delivered under another name", self.prose)
        self.assertIn("whether auto-replies stay on or\noff", self.prose)


if __name__ == "__main__":
    unittest.main()
