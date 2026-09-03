#!/usr/bin/env python3
"""Tests for make-pr preflight. Path lists below are the real changed-file
sets of PRs in this repo (e.g. #89 visual-proof, the 2026-09-01 hook slices)."""
from __future__ import annotations

import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import preflight as pf  # noqa: E402

SCRIPT = os.path.join(os.path.dirname(HERE), "scripts", "preflight.py")

# real: PR #89 "Require actual captures for visual proof"
PR89 = ["product/skills/visual-proof/SKILL.md", "product/skills/visual-proof/tests/fires_example.md"]
# real: prove-it-ship-gate hook slice (2026-09-01)
HOOK_SLICE = ["engine/hooks/prove-it-ship-gate/detect.py", "engine/hooks/prove-it-ship-gate/tests/test_hooks.py",
              "corpus/skills/prove-it-ship-gate/SKILL.md", "install.sh"]
# real: frustration-watchdog wiring slice (2026-09-01)
WIRING_SLICE = ["engine/hooks/frustration-watchdog/claude.hook.json", "engine/hooks/demo-freeze/install_claude_hook.py",
                "install.sh", "tests/test_install.py"]


class TestRepoRoot(unittest.TestCase):
    def test_repo_root_contains_install_sh(self):
        self.assertTrue(os.path.isfile(os.path.join(pf.REPO_ROOT, "install.sh")), pf.REPO_ROOT)


class TestClassify(unittest.TestCase):
    def test_product_skill_pr_is_one_unit(self):
        self.assertEqual(set(pf.classify(PR89)["units"]), {"product-skill"})

    def test_engine_and_neutral_paths(self):
        info = pf.classify(WIRING_SLICE)
        self.assertEqual(set(info["units"]), {"engine-runtime"})
        self.assertEqual(info["neutral"], ["tests/test_install.py"])

    def test_scripts_and_install_sh_are_engine_runtime_like_drafter_config(self):
        info = pf.classify(["scripts/check_codify_has_code.py", "install.sh", ".github/workflows/ci.yml", "docs/x.md"])
        self.assertEqual(set(info["units"]), {"engine-runtime"})
        self.assertEqual(info["neutral"], ["docs/x.md"])

    def test_gates_for_hook_slice_run_hook_and_skill_checks(self):
        cmds = pf.gates_for(HOOK_SLICE)
        self.assertIn(["python3", "scripts/check_hook_test_coverage.py", "engine/hooks/prove-it-ship-gate"], cmds)
        self.assertTrue(any("check_skills_three_harnesses" in " ".join(c) for c in cmds))

    def test_gates_for_rule_prose_include_codify_check(self):
        self.assertEqual(pf.gates_for(PR89)[0], ["python3", "scripts/check_codify_has_code.py"])
        self.assertIn(["python3", "scripts/check_codify_has_code.py"], pf.gates_for(["CLAUDE.md"]))

    def test_gates_for_neutral_only_are_empty(self):
        self.assertEqual(pf.gates_for(["docs/ecosystem.md", "README.md"]), [])

    def test_gates_for_rule_prose_with_base_includes_dated_provenance_check(self):
        self.assertIn(
            ["python3", "scripts/check_no_dated_provenance.py", "--base", "origin/main"],
            pf.gates_for(PR89, base="origin/main"),
        )

    def test_gates_for_rule_prose_without_base_skips_dated_provenance_check(self):
        cmds = pf.gates_for(PR89, base=None)
        self.assertFalse(any("check_no_dated_provenance" in " ".join(c) for c in cmds))


class TestCli(unittest.TestCase):
    def test_flags_mixed_engine_and_corpus_units(self):
        res = subprocess.run([sys.executable, SCRIPT, "--dry-run", "--paths"] + HOOK_SLICE, capture_output=True, text=True)
        self.assertEqual(res.returncode, 1, res.stdout)
        self.assertIn("mixed in one PR", res.stdout)

    def test_passes_single_unit_dry_run(self):
        res = subprocess.run([sys.executable, SCRIPT, "--dry-run", "--paths"] + PR89, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertIn("declare Review Unit: product-skill", res.stdout)

    def test_no_paths_exits_2(self):
        res = subprocess.run([sys.executable, SCRIPT, "--paths"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 2)


if __name__ == "__main__":
    unittest.main()
