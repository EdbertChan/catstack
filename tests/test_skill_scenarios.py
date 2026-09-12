#!/usr/bin/env python3
"""Runs tests/scenarios/*.json through the real hook detectors.

scripts/run_skill_scenarios.py is the interactive entry point ("did my
scenario behave?"). This file is the CI half, so a scenario that stops
matching reality fails the build instead of waiting for someone to run the
script by hand.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import run_skill_scenarios as rs  # noqa: E402


class TestScenarioSuite(unittest.TestCase):
    def test_scenarios_exist(self):
        self.assertGreaterEqual(len(rs.load_scenarios()), 1)

    def test_every_scenario_behaves_as_declared(self):
        for scenario in rs.load_scenarios():
            with self.subTest(scenario=scenario["name"]):
                self.assertEqual(rs.check_scenario(scenario), [], scenario.get("situation", ""))

    def test_every_scenario_declares_at_least_one_expectation(self):
        """A scenario with no expectations passes trivially and proves nothing."""
        keys = ("expect_fire", "expect_silent", "expect_enqueue", "expect_no_enqueue", "expect_skill_auto", "expect_skill_named")
        for scenario in rs.load_scenarios():
            with self.subTest(scenario=scenario["name"]):
                self.assertTrue(
                    any(scenario.get(k) for k in keys),
                    f"{scenario['name']} declares none of {keys}",
                )


class TestRunnerCatchesBreakage(unittest.TestCase):
    """The suite must be able to fail, not just pass."""

    def test_a_wrong_expectation_is_reported(self):
        scenario = {
            "name": "synthetic-inverted",
            "user": "ship it",
            "reply": "Done — deployed to production and the Linear ticket is filed.",
            "expect_silent": ["prove-it-ship-gate"],
        }
        failures = rs.check_scenario(scenario)
        self.assertEqual(len(failures), 1, failures)
        self.assertIn("expected SILENCE", failures[0])

    def test_unknown_skill_name_is_reported(self):
        failures = rs.check_scenario(
            {"name": "x", "reply": "hi", "expect_skill_auto": ["no-such-skill-here"]}
        )
        self.assertEqual(len(failures), 1, failures)
        self.assertIn("no such skill", failures[0])


if __name__ == "__main__":
    unittest.main()
