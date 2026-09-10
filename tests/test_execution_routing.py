#!/usr/bin/env python3
"""Prove cat-mode execution routing decisions are executable, not prose-only."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
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



class TestHarnessRoutingSkillDeferral(unittest.TestCase):
    """cat-mode's table is the fallback. When a harness ships its own
    routing skill (today Invoker's invoker-route-delegation), the router
    names it so the session defers to it instead of this table."""

    @classmethod
    def setUpClass(cls):
        cls.router = load_router()

    def _install(self, home, root, name="invoker-route-delegation", with_skill_md=True):
        skill_dir = os.path.join(home, root, name)
        os.makedirs(skill_dir)
        if with_skill_md:
            with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as handle:
                handle.write("---\nname: route-delegation\n---\n")
        return os.path.join(skill_dir, "SKILL.md")

    def test_no_harness_skill_means_the_catstack_table_decides(self):
        with tempfile.TemporaryDirectory() as home:
            self.assertIsNone(self.router.installed_harness_routing_skill(home))

    def test_invoker_skill_in_any_harness_root_is_found(self):
        for root in self.router.HARNESS_SKILL_ROOTS:
            with self.subTest(root=root), tempfile.TemporaryDirectory() as home:
                expected = self._install(home, root)
                self.assertEqual(self.router.installed_harness_routing_skill(home), expected)

    def test_directory_without_skill_md_does_not_count_as_installed(self):
        with tempfile.TemporaryDirectory() as home:
            self._install(home, ".claude/skills", with_skill_md=False)
            self.assertIsNone(self.router.installed_harness_routing_skill(home))

    def test_unlisted_skill_name_is_not_a_harness_routing_skill(self):
        with tempfile.TemporaryDirectory() as home:
            self._install(home, ".claude/skills", name="some-other-swarm-routing")
            self.assertIsNone(self.router.installed_harness_routing_skill(home))

    def test_cli_reports_defer_to_alongside_the_fallback_route(self):
        with tempfile.TemporaryDirectory() as home:
            expected = self._install(home, ".codex/skills")
            payload = json.dumps({
                "tools": list(self.router.INVOKER_REQUIRED_TOOLS),
                "work_kind": "durable_parallel",
                "produces": ["commit"],
                "home": home,
            })
            out = subprocess.run([sys.executable, SCRIPT, payload], capture_output=True, text=True, check=True)
            result = json.loads(out.stdout)
            self.assertEqual(result["defer_to"], expected)
            self.assertEqual(result["route"], "delegate_invoker")

    def test_cli_reports_no_deferral_when_nothing_is_installed(self):
        with tempfile.TemporaryDirectory() as home:
            payload = json.dumps({"tools": [], "work_kind": "readonly", "produces": ["research"], "home": home})
            out = subprocess.run([sys.executable, SCRIPT, payload], capture_output=True, text=True, check=True)
            self.assertIsNone(json.loads(out.stdout)["defer_to"])


if __name__ == "__main__":
    unittest.main()
