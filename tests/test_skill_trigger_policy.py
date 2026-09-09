#!/usr/bin/env python3
"""Tests for scripts/check_skill_trigger_policy.py.

The manual-without-flag fixture is the real one: product/skills/
admin-bypass-sweep shipped that exact frontmatter shape -- a description
telling the model not to auto-invoke it, with no flag to stop it.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import check_skill_trigger_policy as pol  # noqa: E402

# real shape: admin-bypass-sweep before the flag was added
MANUAL_NO_FLAG = """---
name: admin-bypass-sweep
description: >
  MANUAL, HUMAN-ONLY skill. Force-merges every open PR labeled admin-bypass
  directly to the trunk branch. Do not auto-invoke this skill from a
  natural-language request, a description match, or another agent's
  delegation.
---

# admin-bypass-sweep
"""

MANUAL_WITH_FLAG = MANUAL_NO_FLAG.replace(
    "---\n\n# admin", "disable-model-invocation: true\n---\n\n# admin"
)

AUTO_GATE = """---
name: principle-prove-it
description: "No claim without same-turn evidence."
---

# Prove It
"""

# The phrase appears in the body, not the frontmatter: must not trip the rule.
BODY_MENTION_ONLY = """---
name: docs-about-triggers
description: "Explains the trigger policy."
---

# Docs

A skill that says human-only must not be auto-invoked from a description
match; see admin-bypass-sweep.
"""


def _repo(skills: dict[str, str]) -> Path:
    root = Path(tempfile.mkdtemp())
    for rel, text in skills.items():
        md = root / rel / "SKILL.md"
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text(text, encoding="utf-8")
    return root


class TestManualDeclarationRule(unittest.TestCase):
    def test_manual_declaration_without_flag_is_a_violation(self):
        rows = pol.skills(_repo({"product/skills/admin-bypass-sweep": MANUAL_NO_FLAG}))
        errs = pol.violations(rows)
        self.assertEqual(len(errs), 1, errs)
        self.assertIn("admin-bypass-sweep", errs[0])
        self.assertIn("description match", errs[0])

    def test_manual_declaration_with_flag_passes(self):
        rows = pol.skills(_repo({"product/skills/admin-bypass-sweep": MANUAL_WITH_FLAG}))
        self.assertEqual(pol.violations(rows), [])

    def test_auto_fire_gate_without_manual_wording_passes(self):
        rows = pol.skills(_repo({"corpus/skills/principle-prove-it": AUTO_GATE}))
        self.assertEqual(pol.violations(rows), [])

    def test_manual_wording_in_body_only_does_not_trip_the_rule(self):
        """The rule reads frontmatter, not prose describing another skill."""
        rows = pol.skills(_repo({"product/skills/docs-about-triggers": BODY_MENTION_ONLY}))
        self.assertEqual(pol.violations(rows), [])


class TestInventoryRendering(unittest.TestCase):
    def test_render_splits_auto_from_explicit(self):
        rows = pol.skills(
            _repo(
                {
                    "corpus/skills/principle-prove-it": AUTO_GATE,
                    "product/skills/admin-bypass-sweep": MANUAL_WITH_FLAG,
                }
            )
        )
        block = pol.render(rows)
        auto, explicit = block.split("### Explicit invocation only")
        self.assertIn("principle-prove-it", auto)
        self.assertNotIn("admin-bypass-sweep", auto)
        self.assertIn("admin-bypass-sweep", explicit)

    def test_splice_replaces_only_the_generated_block(self):
        doc = f"keep above\n\n{pol.BEGIN_MARK}\nstale\n{pol.END_MARK}\n\nkeep below\n"
        out = pol.splice(doc, pol.render([("corpus/skills", "x", True, False)]))
        self.assertIn("keep above", out)
        self.assertIn("keep below", out)
        self.assertNotIn("stale", out)

    def test_splice_fails_closed_without_markers(self):
        with self.assertRaises(SystemExit):
            pol.splice("no markers here\n", "block")


class TestRealRepoState(unittest.TestCase):
    def test_this_repo_has_no_manual_without_flag(self):
        self.assertEqual(pol.violations(pol.skills(REPO)), [])


if __name__ == "__main__":
    unittest.main()
