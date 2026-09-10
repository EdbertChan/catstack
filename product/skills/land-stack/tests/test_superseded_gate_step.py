#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SKILL = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
GATE = SKILL_DIR / ".." / ".." / ".." / "scripts" / "check_branch_not_superseded.py"


def load_gate():
    spec = importlib.util.spec_from_file_location("check_branch_not_superseded", GATE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestSupersededGateStep(unittest.TestCase):
    def test_gate_sits_where_the_skill_says(self):
        self.assertIn("/../../../scripts/check_branch_not_superseded.py", SKILL)
        self.assertTrue(GATE.resolve().is_file(), GATE)

    def test_step_runs_before_any_rebase_or_landing(self):
        gate_step = SKILL.index("3. **Before rebasing or resolving conflicts on any PR")
        self.assertLess(SKILL.index("2. **Verify with a guard before any write.**"), gate_step)
        self.assertLess(gate_step, SKILL.index("4. **Land bottom-up.**"))

    def test_exit_codes_in_prose_match_the_gate(self):
        stated = {verdict: int(code) for code, verdict in re.findall(r"Exit (\d+)[^,\n]*, (LIVE|SUPERSEDED|UNCHECKED)", SKILL)}
        self.assertEqual(stated, load_gate().EXIT_CODES)

    def test_superseded_closes_instead_of_resolving(self):
        superseded = SKILL[SKILL.index("SUPERSEDED: do not rebase"):SKILL.index("UNCHECKED: the check did not run")]
        self.assertIn("Close the PR", superseded)
        self.assertIn("naming the PRs that", superseded)

    def test_unchecked_is_never_treated_as_live(self):
        self.assertIn("never treat it as LIVE", " ".join(SKILL.split()))


if __name__ == "__main__":
    unittest.main()
