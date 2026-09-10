#!/usr/bin/env python3
"""Tests for scripts/plan_preflight.py.

The codify-has-code case is the real one: this lever's first run against a
realistic plan reported `check_codify_has_code.py` as unscoped, and reading
scripts/check_codify_has_code.py:91 confirmed it defaults to origin/main while
preflight invoked it with no refs. That is the same vacuous-pass class already
fixed for the coverage gate, found in a sibling nobody had checked.
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import plan_preflight as pp  # noqa: E402

SCRIPT = REPO / "scripts" / "plan_preflight.py"

CORPUS_ONLY = ["corpus/skills/principle-x/SKILL.md", "corpus/skills/principle-x/tests/fires_example.md"]
MIXED = ["corpus/skills/principle-x/SKILL.md", "scripts/check_x.py"]
HOOK_SLICE = ["engine/hooks/verdict-flip-watch/detect.py"]


class TestSlices(unittest.TestCase):
    def test_single_unit_is_one_slice_and_not_mixed(self):
        s = pp.slices_for(CORPUS_ONLY)
        self.assertEqual(list(s["units"]), ["corpus-lesson"])
        self.assertFalse(s["mixed"])
        self.assertEqual(s["slice_count"], 1)

    def test_corpus_plus_engine_is_flagged_mixed(self):
        """preflight.py fails this diff; the plan should say so first."""
        s = pp.slices_for(MIXED)
        self.assertTrue(s["mixed"])
        self.assertEqual(s["slice_count"], 2)
        self.assertEqual(sorted(s["units"]), ["corpus-lesson", "engine-runtime"])

    def test_repo_root_tests_are_neutral_not_a_unit(self):
        s = pp.slices_for(CORPUS_ONLY + ["tests/test_x.py"])
        self.assertEqual(s["neutral"], ["tests/test_x.py"])
        self.assertFalse(s["mixed"])


class TestRefFlagDerivation(unittest.TestCase):
    """Derived from each gate's own argparse, never a list kept here."""

    def test_coverage_gate_accepts_base_and_head(self):
        flags = pp.ref_flags(REPO / "scripts" / "check_skill_test_coverage.py")
        self.assertEqual(flags, ["base", "head"])

    def test_codify_gate_accepts_base(self):
        self.assertEqual(pp.ref_flags(REPO / "scripts" / "check_codify_has_code.py"), ["base"])

    def test_whole_tree_gate_accepts_neither(self):
        self.assertEqual(pp.ref_flags(REPO / "scripts" / "check_ecosystem_boundaries.py"), [])

    def test_missing_file_is_treated_as_whole_tree(self):
        self.assertEqual(pp.ref_flags(REPO / "scripts" / "no_such_gate.py"), [])


class TestGateScoping(unittest.TestCase):
    def test_ref_aware_gate_with_a_base_is_scoped(self):
        gates = pp.gates_for_plan(CORPUS_ONLY, base="origin/main")
        codify = next(g for g in gates if "check_codify_has_code" in g["command"])
        self.assertTrue(codify["scoped"], codify)
        self.assertFalse(codify["whole_tree"])

    def test_ref_aware_gate_without_a_base_is_unscoped(self):
        """No base (the --paths case) means no gate can be scoped."""
        gates = pp.gates_for_plan(CORPUS_ONLY, base=None)
        ref_aware = [g for g in gates if g["accepts_refs"]]
        self.assertTrue(ref_aware, "expected at least one ref-aware gate")
        self.assertTrue(all(not g["scoped"] for g in ref_aware))

    def test_whole_tree_gate_is_never_reported_unscoped(self):
        for g in pp.gates_for_plan(CORPUS_ONLY, base="origin/main"):
            if g["whole_tree"]:
                self.assertFalse(g["scoped"])
                self.assertEqual(g["accepts_refs"], [])

    def test_hook_slice_pulls_in_its_hook_coverage_gate(self):
        cmds = " ".join(g["command"] for g in pp.gates_for_plan(HOOK_SLICE, base="origin/main"))
        self.assertIn("check_hook_test_coverage.py", cmds)


class TestPreflightPassesRefsToBothDiffAwareGates(unittest.TestCase):
    """Regression for the defect this lever found on its first run."""

    def test_codify_gate_receives_the_slice_base(self):
        sys.path.insert(0, str(REPO / "engine" / "skills" / "make-pr" / "scripts"))
        import preflight as pf

        cmds = pf.gates_for(["corpus/skills/principle-x/SKILL.md"], base="origin/main")
        codify = [c for c in cmds if "check_codify_has_code.py" in " ".join(c)]
        self.assertEqual(len(codify), 1, cmds)
        self.assertIn("--base", codify[0])
        self.assertIn("origin/main", codify[0])

    def test_codify_gate_omits_refs_when_there_is_no_base(self):
        sys.path.insert(0, str(REPO / "engine" / "skills" / "make-pr" / "scripts"))
        import preflight as pf

        cmds = pf.gates_for(["corpus/skills/principle-x/SKILL.md"], base=None)
        codify = [c for c in cmds if "check_codify_has_code.py" in " ".join(c)]
        self.assertEqual(codify, [["python3", "scripts/check_codify_has_code.py"]])


class TestBaseStatus(unittest.TestCase):
    def test_origin_main_resolves_and_reports_current(self):
        b = pp.base_status("origin/main")
        self.assertIsNotNone(b["resolved"])
        self.assertTrue(b["current"], b)

    def test_unresolvable_ref_says_so_instead_of_claiming_current(self):
        b = pp.base_status("origin/definitely-not-a-real-ref-xyz")
        self.assertIsNone(b["resolved"])
        self.assertIsNone(b["current"])
        self.assertIn("cannot resolve", b["note"])


class TestCli(unittest.TestCase):
    def _run(self, *args: str):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=REPO
        )

    def test_mixed_units_exit_1_and_say_split_required(self):
        res = self._run("--paths", *MIXED, "--base", "origin/main")
        self.assertEqual(res.returncode, 1, res.stdout)
        self.assertIn("SPLIT REQUIRED", res.stdout)

    def test_json_output_carries_every_section(self):
        res = self._run("--paths", *CORPUS_ONLY, "--base", "origin/main", "--json")
        import json

        plan = json.loads(res.stdout)
        for key in ("paths", "slices", "gates", "base", "unknowns"):
            self.assertIn(key, plan)

    def test_unknowns_are_always_reported(self):
        """A plan with no unknowns has not been examined."""
        res = self._run("--paths", *CORPUS_ONLY, "--base", "origin/main")
        self.assertIn("Unknowns this script cannot answer", res.stdout)

    def test_paths_is_required(self):
        self.assertEqual(self._run().returncode, 2)


if __name__ == "__main__":
    unittest.main()
