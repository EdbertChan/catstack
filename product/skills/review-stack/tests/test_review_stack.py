"""The three review-stack scripts on small temporary git repositories: slicing, the page checks, and the left-behind sweep."""
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


def build(repo, slices_path, prefix="review"):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = build_review_stack.main(repo, "main", "end", prefix, slices_path)
    return rc, out.getvalue()


def write_slices(tmp, second_globs, second_changes=("README.md",)):
    path = os.path.join(tmp, "slices.json")
    json.dump([
        {"slug": "model", "title": "model/: pure code", "body": "The math.", "globs": ["pkg/*", "pkg/model/*", "tests/*"]},
        {"slug": "retire", "title": "Retire the old script", "globs": second_globs, "removals": ["*"], "changes": list(second_changes)},
    ], open(path, "w"))
    return path


class BuildReviewStack(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = make_repo(self.tmp)
        self.meta = os.path.join(self.tmp, "meta.json")

    def test_cuts_the_range_into_branches_whose_last_tree_equals_the_end(self):
        rc, text = build(self.repo, write_slices(self.tmp, ["README.md"]))
        self.assertEqual(rc, 0, text)
        self.assertIn("tree difference between last slice and end: none (identical)", text)
        self.assertIn("Ran 1 test", text)
        self.assertEqual(git(self.repo, "rev-parse", "review/2-retire^{tree}"), git(self.repo, "rev-parse", "end^{tree}"))
        first = git(self.repo, "ls-tree", "-r", "--name-only", "review/1-model").split()
        self.assertIn("pkg/model/math.py", first)
        self.assertIn("old.py", first)
        self.assertNotIn("old.py", git(self.repo, "ls-tree", "-r", "--name-only", "review/2-retire").split())

    def test_fails_when_a_changed_path_is_claimed_by_no_slice(self):
        rc, text = build(self.repo, write_slices(self.tmp, ["docs/*"]))
        self.assertEqual(rc, 1)
        self.assertIn("unclaimed changed paths: ['README.md']", text)

    def test_writes_the_meta_skeleton_with_base_as_the_previous_head_and_keeps_filled_prose(self):
        slices = write_slices(self.tmp, ["README.md"])
        rc, text = build(self.repo, slices)
        self.assertEqual(rc, 0, text)
        self.assertIn("no " + self.meta + " yet: writing a blank skeleton", text)
        record = json.load(open(self.meta))
        self.assertEqual(record["branches"], ["review/1-model", "review/2-retire"])
        self.assertEqual([(s["label"], s["base"], s["head"]) for s in record["slices"]],
                         [("model/: pure code", "main", "review/1-model"), ("Retire the old script", "review/1-model", "review/2-retire")])
        self.assertEqual(record["slices"][0]["claim"], "")
        record["slices"][0]["claim"] = "A package replaces the script."
        record["slices"][0]["head"] = "something-stale"
        json.dump(record, open(self.meta, "w"))
        rc, text = build(self.repo, slices)
        self.assertEqual(rc, 0, text)
        rebuilt = json.load(open(self.meta))
        self.assertEqual(rebuilt["slices"][0]["claim"], "A package replaces the script.")
        self.assertEqual(rebuilt["slices"][0]["head"], "review/1-model")

    def test_deletes_a_prefix_branch_the_build_did_not_produce_and_leaves_other_branches_alone(self):
        git(self.repo, "branch", "review/9-stale", "main")
        git(self.repo, "branch", "feature/keep", "main")
        rc, text = build(self.repo, write_slices(self.tmp, ["README.md"]))
        self.assertEqual(rc, 0, text)
        self.assertIn("stale review/ branches deleted: ['review/9-stale']", text)
        names = git(self.repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/").split()
        self.assertNotIn("review/9-stale", names)
        self.assertIn("feature/keep", names)
        self.assertIn("review/1-model", names)
        rc, text = build(self.repo, write_slices(self.tmp, ["README.md"]))
        self.assertIn("stale review/ branches deleted: none", text)

    def test_fails_when_a_slice_modifies_a_base_path_it_does_not_declare(self):
        rc, text = build(self.repo, write_slices(self.tmp, ["README.md"], second_changes=()))
        self.assertEqual(rc, 1)
        self.assertIn("paths on main the stack modifies: 1; deletes: 1", text)
        self.assertIn("modified base paths no slice declares in its changes: ['retire: README.md']", text)
        rc, text = build(self.repo, write_slices(self.tmp, ["README.md"], second_changes=("README.md",)))
        self.assertEqual(rc, 0, text)
        self.assertIn("modified base paths no slice declares in its changes: none", text)


class StackReviewPage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = make_repo(self.tmp)
        self.meta = os.path.join(self.tmp, "meta.json")
        self.out = os.path.join(self.tmp, "page.html")
        rc, text = build(self.repo, write_slices(self.tmp, ["README.md"]))
        assert rc == 0, text

    def render(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            stack_review_page.main(self.repo, self.out, "--title=Round 9", *args)
        return Path(self.out).read_text(), out.getvalue()

    def fill(self, **fields):
        record = json.load(open(self.meta))
        record["slices"][0].update(fields)
        json.dump(record, open(self.meta, "w"))
        return record

    def test_renders_one_section_per_slice_with_the_claim_block_and_the_diff(self):
        self.fill(lane="behavior", claim="A package replaces the script.", safety="Tests cover the math.")
        page, _ = self.render(f"--slices={self.meta}")
        self.assertEqual(page.count("<section"), 2)
        self.assertIn("<title>Round 9</title>", page)
        self.assertIn("A package replaces the script.", page)
        self.assertIn("Safety invariant (proposed)", page)
        self.assertIn("pkg/model/math.py", page)
        self.assertIn("+def add(a, b):", page)
        self.assertIn("deleted file", page)
        self.assertNotIn("similarity index", page)

    def test_an_empty_required_field_renders_as_not_stated_and_a_filled_one_does_not(self):
        self.fill(claim="A package replaces the script.", alternatives="A shell script; slower to test.")
        page, _ = self.render(f"--slices={self.meta}")
        first = page.split("<section", 2)[1]
        self.assertIn("<dt>Slice rationale</dt><dd>not stated</dd>", first)
        self.assertIn("<dt>Safety invariant (proposed)</dt><dd>not stated</dd>", first)
        self.assertIn("<dt>Alternative considerations</dt><dd>A shell script; slower to test.</dd>", first)
        self.assertNotIn("<dt>Technique</dt>", first)

    def test_refuses_a_head_the_build_did_not_print(self):
        self.fill(head="end")
        with self.assertRaises(SystemExit) as caught:
            self.render(f"--slices={self.meta}")
        self.assertIn("refused: head end of model/: pure code is not a branch the build printed", str(caught.exception))

    def test_refuses_a_base_that_is_not_the_previous_head(self):
        record = json.load(open(self.meta))
        record["slices"][1]["base"] = "main"
        json.dump(record, open(self.meta, "w"))
        with self.assertRaises(SystemExit) as caught:
            self.render(f"--slices={self.meta}")
        self.assertIn("refused: base main of Retire the old script is not the previous head review/1-model", str(caught.exception))

    def test_refuses_a_base_that_is_no_longer_under_its_head(self):
        git(self.repo, "branch", "-f", "review/1-model", "end")
        with self.assertRaises(SystemExit) as caught:
            self.render(f"--slices={self.meta}")
        self.assertIn("refused: review/1-model is not an ancestor of review/2-retire", str(caught.exception))

    def test_refuses_a_hand_written_list_and_accepts_the_build_record(self):
        hand = os.path.join(self.tmp, "hand.json")
        json.dump([{"label": "x", "base": "main", "head": "end"}], open(hand, "w"))
        with self.assertRaises(SystemExit) as caught:
            self.render(f"--slices={hand}")
        self.assertIn("refused: " + hand + " carries no branch record", str(caught.exception))
        page, _ = self.render(f"--slices={self.meta}")
        self.assertEqual(page.count("<section"), 2)

    def test_a_positional_range_gets_the_ancestor_check_and_an_unchecked_line(self):
        with self.assertRaises(SystemExit) as caught:
            self.render("backwards=end..main")
        self.assertIn("refused: end is not an ancestor of main", str(caught.exception))
        page, printed = self.render("whole=main..end")
        self.assertEqual(page.count("<section"), 1)
        self.assertIn("unchecked: end has no build record", printed)


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

    def test_stays_quiet_on_the_builds_own_review_branches_and_flags_a_stale_one(self):
        tmp = tempfile.mkdtemp()
        repo = make_repo(tmp)
        rc, text = build(repo, write_slices(tmp, ["README.md"]))
        self.assertEqual(rc, 0, text)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = left_behind_sweep.main([repo, "end"])
        self.assertEqual(rc, 0, out.getvalue())
        git(repo, "checkout", "-q", "-b", "review/9-stale", "main")
        Path(repo, "stale.py").write_text("print('only here')\n")
        git(repo, "add", "stale.py")
        git(repo, "commit", "-q", "-m", "3/3 a slice from an older cut")
        git(repo, "checkout", "-q", "end")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = left_behind_sweep.main([repo, "end"])
        self.assertEqual(rc, 1)
        self.assertIn("review/9-stale (last commit", out.getvalue())


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

    def test_the_build_owns_the_page_pointers(self):
        self.assertIn("Never write `base` or `head` by hand", self.prose)
        self.assertIn("a modified base path no\nslice declares fails the build", self.prose)
        self.assertIn("deletes `review/*` branches it did not produce", self.prose)
        self.assertIn('"not stated" rather than dropping the row', self.prose)

    def test_treats_an_auto_reply_as_a_draft_that_the_session_checks(self):
        self.assertIn("A reply the agent did not write is a draft, not an answer", self.prose)
        self.assertIn("held, was corrected,\nor was delivered under another name", self.prose)
        self.assertIn("whether auto-replies stay on or\noff", self.prose)


if __name__ == "__main__":
    unittest.main()
