#!/usr/bin/env python3
"""Tests for make-pr preflight. Path lists below are the real changed-file
sets of PRs in this repo (e.g. #89 visual-proof, the 2026-09-01 hook slices)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
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
        info = pf.classify(["scripts/check_codify_has_code.py", "install.sh", ".github/workflows/ci.yml", "docs/ecosystem.md"])
        self.assertEqual(set(info["units"]), {"engine-runtime"})
        self.assertEqual(info["neutral"], ["docs/ecosystem.md"])

    def test_docs_other_than_the_inventory_are_their_own_unit(self):
        info = pf.classify(["engine/hooks/demo/detect.py", "docs/guide.md"])
        self.assertEqual(set(info["units"]), {"engine-runtime", "docs"})

    def test_gates_for_hook_slice_run_hook_and_skill_checks(self):
        cmds = pf.gates_for(HOOK_SLICE)
        self.assertIn(["python3", "scripts/check_hook_test_coverage.py", "engine/hooks/prove-it-ship-gate"], cmds)
        self.assertTrue(any("check_skills_three_harnesses" in " ".join(c) for c in cmds))

    def test_gates_for_rule_prose_include_codify_check(self):
        self.assertEqual(pf.gates_for(PR89)[0], ["python3", "scripts/check_codify_has_code.py"])
        self.assertIn(["python3", "scripts/check_codify_has_code.py"], pf.gates_for(["CLAUDE.md"]))

    def test_gates_for_neutral_only_are_empty(self):
        self.assertEqual(pf.gates_for(["docs/ecosystem.md", "README.md"]), [])

    def test_gates_for_skill_slice_include_trigger_policy(self):
        """A skill slice must run the trigger-policy gate.

        It catches a skill declaring itself human-only with no
        disable-model-invocation behind it -- the admin-bypass-sweep shape,
        where a force-merge skill was reachable by description match.
        """
        cmds = pf.gates_for(["product/skills/how/SKILL.md"])
        self.assertIn(["python3", "scripts/check_skill_trigger_policy.py"], cmds)

    def test_gates_for_skill_slice_include_subagent_scope_contract(self):
        """A skill slice must run the subagent-scope gate.

        It catches a new fan-out skill that never states the scope its
        subagents inherit, which is the boundary a parent cannot review after
        the fact.
        """
        cmds = pf.gates_for(["product/skills/how/SKILL.md"])
        self.assertIn(["python3", "scripts/check_subagent_scope_contract.py"], cmds)

    def test_gates_for_skill_slice_run_the_scenario_suite(self):
        """A skill slice must replay the scenario conversations.

        The unit fixtures prove a hook's own regexes; the scenarios prove a
        realistic conversation actually trips the guard it was written for.
        """
        cmds = pf.gates_for(["product/skills/how/SKILL.md"])
        self.assertIn(["python3", "scripts/run_skill_scenarios.py"], cmds)

    def test_coverage_gate_carries_the_slice_refs(self):
        """Without refs the coverage gate defaults to origin/main and can print
        ok for a stacked slice it never compared -- a vacuous pass. This
        reported a stacked slice as fully green in a real session."""
        cmds = pf.gates_for(["product/skills/how/SKILL.md"], base="origin/main")
        coverage = [c for c in cmds if "check_skill_test_coverage.py" in " ".join(c)]
        self.assertEqual(len(coverage), 1, cmds)
        self.assertEqual(
            coverage[0],
            ["python3", "scripts/check_skill_test_coverage.py",
             "--base", "origin/main", "--head", "HEAD"],
        )

    def test_coverage_gate_omits_refs_when_there_is_no_base(self):
        """Under --paths there is no real git ref, so the flags must be absent
        rather than passed as the string 'None'."""
        cmds = pf.gates_for(["product/skills/how/SKILL.md"], base=None)
        coverage = [c for c in cmds if "check_skill_test_coverage.py" in " ".join(c)]
        self.assertEqual(coverage, [["python3", "scripts/check_skill_test_coverage.py"]])

    def test_codify_gate_carries_the_slice_base(self):
        """Like the coverage gate, codify-has-code is diff-aware: with no refs it
        defaults to origin/main, so on a stacked slice a sibling's code can
        satisfy a prose-only slice's rule. Repro'd on a two-slice stack: the
        gate exits 0 at origin/main and 1 at the real slice base."""
        cmds = pf.gates_for(PR89, base="origin/main")
        codify = [c for c in cmds if "check_codify_has_code.py" in " ".join(c)]
        self.assertEqual(len(codify), 1, cmds)
        self.assertEqual(
            codify[0],
            ["python3", "scripts/check_codify_has_code.py", "--base", "origin/main"],
        )

    def test_codify_gate_omits_the_base_when_there_is_none(self):
        """Under --paths there is no real ref; the flag must be absent, not 'None'."""
        cmds = pf.gates_for(PR89, base=None)
        codify = [c for c in cmds if "check_codify_has_code.py" in " ".join(c)]
        self.assertEqual(codify, [["python3", "scripts/check_codify_has_code.py"]])

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

    def test_fails_engine_and_product_skill_mix_and_names_the_split(self):
        """PR #377's paths: a warning here let a mixed PR publish."""
        pr377 = [
            "engine/hooks/playbook-router/detect.py",
            "engine/hooks/playbook-router/tests/test_hooks.py",
            "product/skills/ship-a-detector/SKILL.md",
            "product/skills/ship-a-detector/tests/test_playbook.py",
            "docs/ecosystem.md",
            "tests/test_install.py",
        ]
        res = subprocess.run([sys.executable, SCRIPT, "--dry-run", "--paths"] + pr377, capture_output=True, text=True)
        self.assertEqual(res.returncode, 1, res.stdout)
        self.assertIn("split     engine-runtime: engine/hooks/playbook-router/detect.py", res.stdout)
        self.assertIn("split     product-skill: product/skills/ship-a-detector/SKILL.md", res.stdout)

    def test_fails_a_hook_that_also_edits_the_root_readme_and_names_the_split(self):
        pr506 = [
            "README.md",
            "docs/ecosystem.md",
            "engine/hooks/handoff-needs-smoke-test/detect.py",
            "engine/hooks/handoff-needs-smoke-test/tests/test_hooks.py",
            "install.sh",
            "tests/test_install.py",
        ]
        res = subprocess.run([sys.executable, SCRIPT, "--dry-run", "--paths"] + pr506, capture_output=True, text=True)
        self.assertEqual(res.returncode, 1, res.stdout)
        self.assertIn("split     docs: README.md", res.stdout)
        self.assertIn("split     engine-runtime: engine/hooks/handoff-needs-smoke-test/detect.py", res.stdout)

    def test_a_hook_with_its_inventory_row_and_install_test_passes(self):
        res = subprocess.run(
            [sys.executable, SCRIPT, "--dry-run", "--paths", "engine/hooks/demo/detect.py", "docs/ecosystem.md", "tests/test_install.py"],
            capture_output=True, text=True,
        )
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertIn("declare Review Unit: engine-runtime", res.stdout)

    def test_unreadable_unit_rules_fail_as_unchecked_not_pass(self):
        res = subprocess.run(
            [sys.executable, SCRIPT, "--dry-run", "--config", "/nonexistent/drafter.config.json", "--paths"] + PR89,
            capture_output=True, text=True,
        )
        self.assertEqual(res.returncode, pf.UNCHECKED_EXIT, res.stdout + res.stderr)
        self.assertIn("unchecked review units", res.stdout)
        self.assertNotIn("ok      preflight passed", res.stdout)

    def test_a_copy_outside_the_repo_classifies_with_an_explicit_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = os.path.join(tmp, "preflight.py")
            shutil.copy2(SCRIPT, copy)
            res = subprocess.run(
                [sys.executable, copy, "--dry-run", "--config", os.path.join(pf.REPO_ROOT, "drafter.config.json"),
                 "--paths", "engine/hooks/demo/detect.py", "README.md"],
                capture_output=True, text=True, cwd=tmp,
            )
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("split     docs: README.md", res.stdout)


class TestRulesMatchDrafterCore(unittest.TestCase):
    def test_every_tracked_path_gets_the_same_units_as_the_pr_body_checker(self):
        paths = subprocess.run(
            ["git", "-C", pf.REPO_ROOT, "ls-files", "-z"], capture_output=True, text=True, check=True,
        ).stdout.split("\0")
        paths = [p for p in paths if p] + [
            ".mergify.yml", "package-lock.json", "a/b/yarn.lock", "tsconfig.base.json", "e2e/foo/bar.ts",
            "x/.hidden/y.md", ".github/workflows/ci.yml", "corpus/skills/a/tests/t.py", "docs/guide.md",
        ]
        script = (
            "import { classifyReviewUnitsForPath, loadDrafterConfig } from '@neko-catpital-labs/drafter-core';"
            "const paths = JSON.parse(await new Response(process.stdin).text());"
            "const config = await loadDrafterConfig({});"
            "console.log(JSON.stringify(paths.map((p) => classifyReviewUnitsForPath(p, config))));"
        )
        res = subprocess.run(
            ["node", "--input-type=module", "-e", script], input=json.dumps(paths),
            capture_output=True, text=True, cwd=pf.REPO_ROOT,
        )
        self.assertEqual(res.returncode, 0, "drafter-core could not run, so parity is unchecked (run npm ci): " + res.stderr)
        expected = json.loads(res.stdout)
        rules = pf.load_unit_rules(pf.DEFAULT_CONFIG)
        differ = [(p, pf.review_units_for(p, rules), e) for p, e in zip(paths, expected) if pf.review_units_for(p, rules) != e]
        self.assertEqual(differ, [])

    def test_passes_single_unit_dry_run(self):
        res = subprocess.run([sys.executable, SCRIPT, "--dry-run", "--paths"] + PR89, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertIn("declare Review Unit: product-skill", res.stdout)

    def test_no_paths_exits_2(self):
        res = subprocess.run([sys.executable, SCRIPT, "--paths"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 2)


if __name__ == "__main__":
    unittest.main()
