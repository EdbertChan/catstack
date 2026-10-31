import os
import sys
import tempfile
import unittest

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import fanout_complete as fc  # noqa: E402

DEFAULT_BUDGET = 20_000_000


class TestReflectLensBudget(unittest.TestCase):
    def nothing_set(self, **extra):
        """An environment where no source defines the flag, not even a home file."""
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        return {"HOME": home.name, **extra}

    def test_under_budget_runs_full_ordered_set(self):
        plan = fc.lens_plan(99, 100)
        self.assertEqual(plan["expected"], list(fc.ALL_LENSES))
        self.assertEqual(plan["omitted"], [])
        self.assertFalse(plan["reduced"])

    def test_over_budget_runs_required_set_and_names_omissions(self):
        plan = fc.lens_plan(101, 100)
        self.assertEqual(plan["expected"], list(fc.REQUIRED_LENSES))
        self.assertEqual(plan["omitted"], ["Tooling", "History", "Divergent"])
        self.assertTrue(plan["reduced"])

    def test_registered_default_is_twenty_million_tokens(self):
        flags = fc.load_flags_module()
        self.assertEqual(
            flags.FLAG_DEFAULTS[flags.REFLECT_LENS_BUDGET], str(DEFAULT_BUDGET))
        self.assertIn(flags.REFLECT_LENS_BUDGET, flags.BEHAVIOR_FLAGS)

    def test_unset_budget_reduces_an_eighty_million_token_session(self):
        plan = fc.lens_plan_from_env(80_000_000, self.nothing_set())
        self.assertEqual(plan["expected"], list(fc.REQUIRED_LENSES))
        self.assertEqual(plan["omitted"], ["Tooling", "History", "Divergent"])
        self.assertTrue(plan["reduced"])
        self.assertEqual(plan["budget"], DEFAULT_BUDGET)

    def test_unset_budget_keeps_the_full_set_on_a_three_million_token_session(self):
        plan = fc.lens_plan_from_env(3_000_000, self.nothing_set())
        self.assertEqual(plan["expected"], list(fc.ALL_LENSES))
        self.assertEqual(plan["omitted"], [])
        self.assertFalse(plan["reduced"])
        self.assertEqual(plan["budget"], DEFAULT_BUDGET)

    def test_explicit_budget_overrides_the_default_and_keeps_the_full_set(self):
        plan = fc.lens_plan_from_env(
            80_000_000,
            self.nothing_set(CATSTACK_REFLECT_LENS_BUDGET="1000000000"),
        )
        self.assertEqual(plan["expected"], list(fc.ALL_LENSES))
        self.assertFalse(plan["reduced"])
        self.assertEqual(plan["budget"], 1_000_000_000)

    def test_repo_env_file_still_beats_the_default(self):
        with tempfile.TemporaryDirectory() as repo:
            os.makedirs(os.path.join(repo, ".git"))
            with open(os.path.join(repo, ".env"), "w", encoding="utf-8") as handle:
                handle.write("CATSTACK_REFLECT_LENS_BUDGET=1000000000\n")
            plan = fc.lens_plan_from_env(80_000_000, self.nothing_set(), cwd=repo)
        self.assertFalse(plan["reduced"])
        self.assertEqual(plan["budget"], 1_000_000_000)

    def test_malformed_budget_is_still_an_error(self):
        with self.assertRaises(ValueError):
            fc.lens_plan_from_env(
                80_000_000, self.nothing_set(CATSTACK_REFLECT_LENS_BUDGET="plenty"))

    def test_non_positive_budget_is_still_an_error(self):
        with self.assertRaises(ValueError):
            fc.lens_plan_from_env(
                80_000_000, self.nothing_set(CATSTACK_REFLECT_LENS_BUDGET="0"))

    def test_unreadable_env_file_is_an_error_naming_the_file(self):
        with tempfile.TemporaryDirectory() as repo:
            os.makedirs(os.path.join(repo, ".git"))
            os.makedirs(os.path.join(repo, ".env"))
            with self.assertRaises(ValueError) as raised:
                fc.lens_plan_from_env(80_000_000, self.nothing_set(), cwd=repo)
            self.assertIn(os.path.join(repo, ".env"), str(raised.exception))

    def test_environment_budget_reduces_and_status_names_every_omission(self):
        plan = fc.lens_plan_from_env(80_000_000, {"CATSTACK_REFLECT_LENS_BUDGET": "1000000"})
        self.assertEqual(
            fc.reduced_status(80_000_000, 1_000_000, plan),
            "reduced reflect: ran Judgment, Cost, Frustration, omitted Tooling, History, Divergent (session 80000000 tokens over budget 1000000)",
        )

    def test_incident_scale_session_reduces(self):
        plan = fc.lens_plan(80_000_000, 1_000_000)
        self.assertTrue(plan["reduced"])
        self.assertEqual(plan["expected"], ["Judgment", "Cost", "Frustration"])

    def test_recorded_reduced_pass_is_complete(self):
        plan = fc.lens_plan(101, 100)
        outcome, missing, unexpected = fc.verdict(plan["expected"], plan["expected"])
        self.assertEqual((outcome, missing, unexpected), (fc.COMPLETE, [], []))

    def test_recorded_reduced_pass_missing_required_lens_is_incomplete(self):
        plan = fc.lens_plan(101, 100)
        outcome, missing, _ = fc.verdict(plan["expected"], ["Judgment", "Cost"])
        self.assertEqual(outcome, fc.INCOMPLETE)
        self.assertEqual(missing, ["Frustration"])


if __name__ == "__main__":
    unittest.main()
