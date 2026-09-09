#!/usr/bin/env python3
"""Tests for scripts/check_subagent_scope_contract.py.

The negation fixtures are the real false positives a looser pattern produced
on this repo: principle-build-the-lever tells you NOT to fan out delegates,
and principle-trace-token-burn-loop mentions re-spawning as a cost. Both were
flagged as spawners before the per-line negation guard existed.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import check_subagent_scope_contract as sc  # noqa: E402

BARE_SPAWNER = """---
name: bare-fanout
description: "Fans out workers."
---

# Bare fanout

Spawn all explorers in a single message, one worker per package.
"""

SPAWNER_NAMING_PRINCIPLE = BARE_SPAWNER.replace(
    "# Bare fanout", "# Bare fanout\n\nInherits principle-subagent-inherits-scope."
)

SPAWNER_CITING_CONTRACT = BARE_SPAWNER.replace(
    "# Bare fanout",
    "# Bare fanout\n\nEach worker returns the shape in finding-shape.md.",
)

# real: corpus/skills/principle-build-the-lever line 16
NEGATED_FANOUT = """---
name: principle-build-the-lever
description: "Build the script."
---

# Build the Lever

- A deterministic lever beats fan-out. If the tool can process every unit in
  one pass, run it yourself; don't fan out delegates to hand-apply what a
  script can do.
"""

# real: corpus/skills/principle-trace-token-burn-loop line 14
COST_MENTION = """---
name: principle-trace-token-burn-loop
description: "Trace the burn."
---

# Trace the loop

The same context gets re-sent on every turn (including after
re-spawning the agent).
"""

NOT_A_SPAWNER = """---
name: spike-and-validate
description: "Build a throwaway."
---

# Spike

Build the smallest thing that could fail, run it, paste the output.
"""


def _repo(skills: dict[str, str]) -> Path:
    root = Path(tempfile.mkdtemp())
    for rel, text in skills.items():
        md = root / rel / "SKILL.md"
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text(text, encoding="utf-8")
    return root


class TestSpawnerDetection(unittest.TestCase):
    def test_bare_spawner_is_a_violation(self):
        root = _repo({"product/skills/bare-fanout": BARE_SPAWNER})
        errs = sc.violations(root, allow=set())
        self.assertEqual(len(errs), 1, errs)
        self.assertIn("bare-fanout", errs[0])

    def test_naming_the_principle_satisfies_the_gate(self):
        root = _repo({"product/skills/bare-fanout": SPAWNER_NAMING_PRINCIPLE})
        self.assertEqual(sc.violations(root, allow=set()), [])

    def test_citing_the_contract_reference_satisfies_the_gate(self):
        root = _repo({"product/skills/bare-fanout": SPAWNER_CITING_CONTRACT})
        self.assertEqual(sc.violations(root, allow=set()), [])

    def test_allowlist_grandfathers_a_bare_spawner(self):
        root = _repo({"engine/skills/reflect": BARE_SPAWNER})
        self.assertEqual(sc.violations(root, allow={"engine/skills/reflect"}), [])

    def test_non_spawner_is_not_flagged(self):
        root = _repo({"product/skills/spike-and-validate": NOT_A_SPAWNER})
        self.assertEqual(sc.spawners(root), [])


class TestNegationGuard(unittest.TestCase):
    def test_telling_you_not_to_fan_out_is_not_a_spawn_instruction(self):
        root = _repo({"corpus/skills/principle-build-the-lever": NEGATED_FANOUT})
        self.assertEqual(sc.spawners(root), [])

    def test_pricing_a_respawn_is_not_a_spawn_instruction(self):
        root = _repo({"corpus/skills/principle-trace-token-burn-loop": COST_MENTION})
        self.assertEqual(sc.spawners(root), [])


class TestRealRepoState(unittest.TestCase):
    def test_repo_passes_with_its_own_allowlist(self):
        self.assertEqual(sc.violations(REPO, sc.allowlisted()), [])

    def test_the_four_investigation_products_state_the_contract(self):
        found = set(sc.spawners(REPO))
        for rel in (
            "product/skills/how",
            "product/skills/why",
            "product/skills/alternatives-considered",
        ):
            self.assertIn(rel, found, f"{rel} should be detected as a spawner")
            self.assertTrue(sc.states_contract(REPO, rel), f"{rel} lacks the contract")


if __name__ == "__main__":
    unittest.main()
