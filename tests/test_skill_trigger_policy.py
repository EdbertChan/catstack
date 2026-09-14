#!/usr/bin/env python3
"""Tests for scripts/ci/check_skill_trigger_policy.py.

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
sys.path.insert(0, str(REPO / "scripts" / "ci"))
import check_skill_trigger_policy as pol  # noqa: E402

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


class TestGeneratorMoved(unittest.TestCase):
    """The block's begin marker names this script's own path. Moving the
    script must not make an otherwise identical block read as stale."""

    ROWS = [("corpus/skills", "x", True, False)]

    def _doc(self, begin_line: str, body_rows=None) -> str:
        block = pol.render(body_rows or self.ROWS)
        rest = block.split("\n", 1)[1]
        return f"above\n\n{begin_line}\n{rest}\n\nbelow\n"

    def test_block_whose_marker_names_the_old_path_of_a_moved_script_is_current(self):
        old_begin = pol.BEGIN_MARK.replace("check_skill_trigger_policy.py", "old/check_skill_trigger_policy.py")
        doc = self._doc(old_begin)
        self.assertTrue(pol.block_is_current(doc, pol.render(self.ROWS), exists=lambda path: True))

    def test_block_with_the_canonical_marker_is_current(self):
        self.assertTrue(pol.block_is_current(self._doc(pol.BEGIN_MARK), pol.render(self.ROWS), exists=lambda path: False))

    def test_marker_naming_a_different_script_is_stale(self):
        other = pol.BEGIN_MARK.replace("check_skill_trigger_policy.py", "check_something_else.py")
        self.assertFalse(pol.block_is_current(self._doc(other), pol.render(self.ROWS), exists=lambda path: True))

    def test_marker_path_that_does_not_exist_is_stale(self):
        old_begin = pol.BEGIN_MARK.replace("check_skill_trigger_policy.py", "old/check_skill_trigger_policy.py")
        self.assertFalse(pol.block_is_current(self._doc(old_begin), pol.render(self.ROWS), exists=lambda path: False))

    def test_changed_skill_list_is_stale_even_with_a_moved_marker(self):
        old_begin = pol.BEGIN_MARK.replace("check_skill_trigger_policy.py", "old/check_skill_trigger_policy.py")
        doc = self._doc(old_begin, body_rows=[("corpus/skills", "y", True, False)])
        self.assertFalse(pol.block_is_current(doc, pol.render(self.ROWS), exists=lambda path: True))

    def test_splice_replaces_a_block_whose_marker_names_an_old_path(self):
        old_begin = pol.BEGIN_MARK.replace("check_skill_trigger_policy.py", "old/check_skill_trigger_policy.py")
        out = pol.splice(self._doc(old_begin), pol.render(self.ROWS))
        self.assertIn(pol.BEGIN_MARK, out)
        self.assertNotIn(old_begin, out)

class TestRealRepoState(unittest.TestCase):
    def test_this_repo_has_no_manual_without_flag(self):
        self.assertEqual(pol.violations(pol.skills(REPO)), [])


if __name__ == "__main__":
    unittest.main()
