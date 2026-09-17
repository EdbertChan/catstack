"""This skill tells the parent to spawn a subagent, so it owes the scope contract.

Regression for the repo-wide gate in
scripts/ci/check_subagent_scope_contract.py: the over-cap stub instruction
("spawn a fresh read-only subagent") makes this skill a spawner, and a spawner
that names neither principle-subagent-inherits-scope nor the contract in
finding-shape.md fails that gate.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
SKILL_REL = "corpus/skills/principle-guard-the-context-window"

sys.path.insert(0, str(REPO / "scripts" / "ci"))
import check_subagent_scope_contract as sc  # noqa: E402


class TestSpawnInstructionStatesScope(unittest.TestCase):
    def test_this_skill_is_detected_as_a_spawner(self):
        self.assertIn(SKILL_REL, sc.spawners(REPO))

    def test_this_skill_states_the_scope_contract(self):
        self.assertTrue(
            sc.states_contract(REPO, SKILL_REL),
            f"{SKILL_REL}/SKILL.md must name {sc.PRINCIPLE} or {sc.CONTRACT_REF}",
        )

    def test_this_skill_is_not_on_the_debt_allowlist(self):
        allow = sc.allowlisted()
        self.assertNotIn(SKILL_REL, allow)
        self.assertNotIn(SKILL_REL.split("/")[-1], allow)
