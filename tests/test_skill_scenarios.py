#!/usr/bin/env python3
"""Runs tests/scenarios/*.json through the real hook detectors.

scripts/run_skill_scenarios.py is the interactive entry point ("did my
scenario behave?"). This file is the CI half, so a scenario that stops
matching reality fails the build instead of waiting for someone to run the
script by hand.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_a_wrong_silence_on_an_opt_in_hook_is_reported_with_the_flag_off(self):
        """Silence must come from the detector, not from the hook being off.

        verdict-flip-watch and wrong-check-reflect do nothing unless
        CATSTACK_REFLECT_ENFORCEMENT is on. If the runner left that to the
        caller's environment, every expect_silent / expect_no_enqueue on those
        hooks would pass on any machine without the flag -- a check that could
        not run, reporting clean. Inverting two scenarios that really fire
        proves the runner switches the flag on itself.
        """
        by_name = {s["name"]: s for s in rs.load_scenarios()}
        flip = dict(by_name["stale-green-caught-without-any-admission"])
        flip["expect_silent"] = flip.pop("expect_fire")
        judge = dict(by_name["admission-in-unlisted-wording-still-asks-the-judge"])
        judge["expect_no_enqueue"] = judge.pop("expect_enqueue")
        with patch.dict(os.environ, {"CATSTACK_REFLECT_ENFORCEMENT": "0"}):
            flip_failures = rs.check_scenario(flip)
            judge_failures = rs.check_scenario(judge)
            self.assertEqual(os.environ["CATSTACK_REFLECT_ENFORCEMENT"], "0")
        self.assertTrue(any("expected SILENCE" in f for f in flip_failures), flip_failures)
        self.assertTrue(any("expected NO judge job" in f for f in judge_failures), judge_failures)

    def test_unknown_skill_name_is_reported(self):
        failures = rs.check_scenario(
            {"name": "x", "reply": "hi", "expect_skill_auto": ["no-such-skill-here"]}
        )
        self.assertEqual(len(failures), 1, failures)
        self.assertIn("no such skill", failures[0])


if __name__ == "__main__":
    unittest.main()
