import os
import sys
import tempfile
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

    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)

    def plan_from(self, session_tokens, environ):
        """Plan with no repo .env and an empty home, so only `environ` and the default count."""
        return fc.lens_plan_from_env(session_tokens, environ, cwd=None, home=self.home.name)

    def test_unset_budget_reduces_an_80m_session(self):
        plan = self.plan_from(80_000_000, {})
        self.assertEqual(plan["expected"], list(fc.REQUIRED_LENSES))
        self.assertTrue(plan["reduced"])

    def test_unset_budget_keeps_the_full_set_for_a_3m_session(self):
        plan = self.plan_from(3_000_000, {})
        self.assertEqual(plan["expected"], list(fc.ALL_LENSES))
        self.assertFalse(plan["reduced"])

    def test_explicit_budget_restores_the_full_set_on_an_80m_session(self):
        plan = self.plan_from(80_000_000, {"CATSTACK_REFLECT_LENS_BUDGET": "1000000000"})
        self.assertEqual(plan["expected"], list(fc.ALL_LENSES))
        self.assertFalse(plan["reduced"])

    def test_home_env_file_budget_overrides_the_default(self):
        with open(os.path.join(self.home.name, ".catstack.env"), "w", encoding="utf-8") as handle:
            handle.write("CATSTACK_REFLECT_LENS_BUDGET=1000000000\n")
        plan = self.plan_from(80_000_000, {})
        self.assertFalse(plan["reduced"])

    def test_unreadable_home_env_file_is_an_error_not_the_default(self):
        os.mkdir(os.path.join(self.home.name, ".catstack.env"))
        with self.assertRaisesRegex(ValueError, "unchecked"):
            self.plan_from(80_000_000, {})

    def test_malformed_or_non_positive_budget_is_an_error(self):
        for value in ("lots", "0", "-5"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.plan_from(80_000_000, {"CATSTACK_REFLECT_LENS_BUDGET": value})

    def test_environment_budget_reduces_and_status_names_every_omission(self):
        plan = self.plan_from(80_000_000, {"CATSTACK_REFLECT_LENS_BUDGET": "1000000"})
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
