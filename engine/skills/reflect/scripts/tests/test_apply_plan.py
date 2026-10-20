#!/usr/bin/env python3
"""apply_plan.py groups Accepted target paths the way make-pr preflight will.

Fail-before this script: step 5 grouped worktrees by owning repo only, so a
pass whose Accepted items touched a corpus skill and two engine skills got one
worktree, and preflight split the resulting slice into two PRs after the
edits were made. The plan has to say "two worktrees" before anything spawns.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
import apply_plan  # noqa: E402

SCRIPT = os.path.join(SCRIPTS, "apply_plan.py")
PRIOR_PASS_PATHS = [
    "/".join(["corpus", "skills", "cat-mode", "SKILL.md"]),
    "engine/skills/reflect/SKILL.md",
    "engine/skills/draft-pr/SKILL.md",
]
ENGINE_PATHS = [
    "engine/skills/reflect/scripts/token_audit.py",
    "engine/hooks/_sdk/runtime.py",
    "engine/hooks/wait-needs-wakeup/detect.py",
]


def run(*args):
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True, check=False)


class TestPlanRowsFollowReviewUnits(unittest.TestCase):
    def test_prior_pass_paths_across_two_units_plan_two_worktrees(self):
        rows = apply_plan.plan(PRIOR_PASS_PATHS, topic="sibling", stamp="20261018")
        self.assertEqual(len(rows), 2)
        self.assertEqual([row["unit"] for row in rows], ["corpus-lesson", "engine-runtime"])
        self.assertEqual(rows[0]["paths"], PRIOR_PASS_PATHS[:1])
        self.assertEqual(rows[1]["paths"], PRIOR_PASS_PATHS[1:])
        self.assertTrue(rows[0]["worktree"].endswith(os.path.join(".worktrees", "reflect-sibling-corpus-lesson")))
        self.assertEqual(rows[1]["branch"], "reflect/sibling-engine-runtime-20261018")

    def test_three_engine_paths_plan_one_worktree(self):
        rows = apply_plan.plan(ENGINE_PATHS, topic="unchecked-hooks", stamp="20261019")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["unit"], "engine-runtime")
        self.assertEqual(rows[0]["paths"], ENGINE_PATHS)

    def test_a_test_path_rides_along_with_its_engine_unit(self):
        rows = apply_plan.plan(
            ["engine/hooks/_sdk/runtime.py", "engine/hooks/_sdk/tests/test_runtime_unchecked.py"],
            topic="t", stamp="20261019",
        )
        self.assertEqual([row["unit"] for row in rows], ["engine-runtime"])
        self.assertEqual(len(rows[0]["paths"]), 2)

    def test_absolute_path_inside_this_checkout_is_this_repo(self):
        absolute = os.path.join(apply_plan.REPO_ROOT, "engine", "hooks", "_sdk", "runtime.py")
        rows = apply_plan.plan([absolute, "engine/hooks/_sdk/render.py"], topic="t", stamp="20261019")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["paths"], ["engine/hooks/_sdk/runtime.py", "engine/hooks/_sdk/render.py"])


class TestCommandLine(unittest.TestCase):
    def test_prints_one_row_per_unit_and_exits_0(self):
        res = run("--topic", "sibling", "--date", "20261018", *PRIOR_PASS_PATHS)
        self.assertEqual(res.returncode, 0, res.stderr)
        rows = [line for line in res.stdout.splitlines() if line.startswith("row\t")]
        self.assertEqual(len(rows), 2)
        self.assertIn("plan\t2 worktree(s)", res.stdout)

    def test_json_rows_carry_repo_unit_worktree_branch_paths(self):
        res = run("--json", "--date", "20261019", *ENGINE_PATHS)
        self.assertEqual(res.returncode, 0, res.stderr)
        rows = json.loads(res.stdout)
        self.assertEqual(set(rows[0]), {"repo", "unit", "worktree", "branch", "paths"})

    def test_item_with_no_path_exits_1_and_names_the_item(self):
        res = run("--item", "A1=engine/hooks/_sdk/runtime.py", "--item", "A2=")
        self.assertEqual(res.returncode, 1)
        self.assertIn("A2", res.stderr)

    def test_no_paths_at_all_exits_1(self):
        res = run()
        self.assertEqual(res.returncode, 1)
        self.assertIn("no target paths", res.stderr)


if __name__ == "__main__":
    unittest.main()
