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


if __name__ == "__main__":
    unittest.main()
