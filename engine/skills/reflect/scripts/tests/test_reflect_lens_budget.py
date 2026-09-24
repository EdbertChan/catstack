import os
import sys
import unittest

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import fanout_complete as fc  # noqa: E402


class TestReflectLensBudget(unittest.TestCase):
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

    def test_unset_budget_preserves_unchanged_behavior(self):
        plan = fc.lens_plan_from_env(80_000_000, {})
        self.assertEqual(plan["expected"], list(fc.ALL_LENSES))
        self.assertFalse(plan["reduced"])

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
