#!/usr/bin/env python3
"""Prove cat-mode execution routing decisions are executable, not prose-only."""

from __future__ import annotations

import importlib.util
import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO_ROOT, "corpus", "skills", "cat-mode", "scripts", "route_execution.py")


def load_router():
    spec = importlib.util.spec_from_file_location("route_execution", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestExecutionRouting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.router = load_router()

    def test_unavailable_stays_local(self):
        route = self.router.route_execution(tools=[], work_kind="approved_plan")
        self.assertEqual(route, "local")
        self.assertEqual(self.router.handoff_steps_for(route), ("stay_local",))

    def test_partial_tools_still_local(self):
        route = self.router.route_execution(
            tools=["invoker_prepare_plan_review"],
            work_kind="durable_parallel",
        )
        self.assertEqual(route, "local")

    def test_small_local_stays_local_even_with_invoker(self):
        tools = list(self.router.INVOKER_REQUIRED_TOOLS)
        for kind in ("small_local", "readonly"):
            with self.subTest(kind=kind):
                self.assertEqual(
                    self.router.route_execution(tools=tools, work_kind=kind),
                    "local",
                )

    def test_post_land_babysit_aliases_are_durable(self):
        tools = list(self.router.INVOKER_REQUIRED_TOOLS)
        for kind in ("post_land_babysit", "named_execution_backlog"):
            with self.subTest(kind=kind):
                self.assertEqual(self.router.normalize_work_kind(kind), "durable_parallel")
                self.assertEqual(
                    self.router.route_execution(tools=tools, work_kind=kind),
                    "delegate_invoker",
                )

    def test_durable_and_approved_delegate(self):
        tools = list(self.router.INVOKER_REQUIRED_TOOLS) + [
            "invoker_wait_for_workflow",
            "invoker_get_workflow",
            "invoker_list_tasks",
        ]
        for kind in ("approved_plan", "durable_parallel"):
            with self.subTest(kind=kind):
                route = self.router.route_execution(tools=tools, work_kind=kind)
                self.assertEqual(route, "delegate_invoker")
                self.assertEqual(
                    self.router.handoff_steps_for(route),
                    self.router.DELEGATE_HANDOFF_STEPS,
                )
                self.assertIn("invoker_prepare_plan_review", self.router.handoff_steps_for(route))
                self.assertIn("await_one_user_approval", self.router.handoff_steps_for(route))
                self.assertIn("invoker_submit_plan", self.router.handoff_steps_for(route))


class TestDelegationPrecedence(unittest.TestCase):
    """The Subagents default and Execution routing both fire on separable,
    parallel, PR-worthy work. route_delegation is the tiebreak: anything that
    publishes goes back to the routing table, so a fan-out cannot be
    self-authorized by separability alone."""

    @classmethod
    def setUpClass(cls):
        cls.router = load_router()

    def test_publishing_work_never_fans_out_to_subagents(self):
        tools = list(self.router.INVOKER_REQUIRED_TOOLS)
        for output in sorted(self.router.PUBLISHING_OUTPUTS):
            with self.subTest(produces=output):
                route = self.router.route_delegation(
                    tools=tools, work_kind="durable_parallel", produces=[output]
                )
                self.assertNotEqual(route, "subagent_fanout")
                self.assertEqual(route, "delegate_invoker")

    def test_separable_parallel_commit_producing_work_routes_to_invoker(self):
        """The eight-subagent shape: separable, parallel, each unit a
        PR-worthy commit, invoker available."""
        tools = list(self.router.INVOKER_REQUIRED_TOOLS)
        self.assertEqual(
            self.router.route_delegation(
                tools=tools, work_kind="durable_parallel", produces=["commit", "pull_request"]
            ),
            "delegate_invoker",
        )

    def test_publishing_work_without_invoker_still_leaves_the_subagent_default(self):
        route = self.router.route_delegation(
            tools=[], work_kind="durable_parallel", produces=["pull_request"]
        )
        self.assertEqual(route, self.router.route_execution(tools=[], work_kind="durable_parallel"))
        self.assertNotEqual(route, "subagent_fanout")

    def test_durable_aliases_publish_even_when_produces_says_nothing(self):
        tools = list(self.router.INVOKER_REQUIRED_TOOLS)
        for kind in ("post_land_babysit", "named_execution_backlog", "approved_plan"):
            with self.subTest(work_kind=kind):
                self.assertTrue(self.router.publishes(work_kind=kind, produces=["none"]))
                self.assertEqual(
                    self.router.route_delegation(tools=tools, work_kind=kind, produces=["none"]),
                    "delegate_invoker",
                )

    def test_non_publishing_work_keeps_the_subagent_fanout_default(self):
        tools = list(self.router.INVOKER_REQUIRED_TOOLS)
        for output in sorted(self.router.NON_PUBLISHING_OUTPUTS):
            with self.subTest(produces=output):
                self.assertEqual(
                    self.router.route_delegation(
                        tools=tools, work_kind="readonly", produces=[output]
                    ),
                    "subagent_fanout",
                )

    def test_fanout_handoff_steps_carry_the_isolation_and_transcript_checks(self):
        steps = self.router.handoff_steps_for("subagent_fanout")
        self.assertEqual(steps, self.router.SUBAGENT_FANOUT_STEPS)
        self.assertIn("spawn_worktree_isolated_subagents", steps)
        self.assertIn("grep_transcripts_for_writes", steps)
        self.assertNotEqual(steps, self.router.DELEGATE_HANDOFF_STEPS)

    def test_undeclared_output_is_unchecked_not_clean(self):
        tools = list(self.router.INVOKER_REQUIRED_TOOLS)
        with self.assertRaises(ValueError):
            self.router.route_delegation(tools=tools, work_kind="durable_parallel", produces=[])

    def test_unknown_output_name_raises_instead_of_defaulting_to_fanout(self):
        tools = list(self.router.INVOKER_REQUIRED_TOOLS)
        with self.assertRaises(ValueError):
            self.router.route_delegation(
                tools=tools, work_kind="durable_parallel", produces=["maybe_a_pr"]
            )

    def test_unknown_work_kind_still_raises(self):
        with self.assertRaises(ValueError):
            self.router.route_delegation(tools=[], work_kind="whatever", produces=["none"])


if __name__ == "__main__":
    unittest.main()
