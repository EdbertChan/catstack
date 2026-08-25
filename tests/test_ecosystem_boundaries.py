#!/usr/bin/env python3
"""Positive + negative tests for check_ecosystem_boundaries."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import check_ecosystem_boundaries as ceb  # noqa: E402


def _write(path: str, text: str = "# x\n") -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def _minimal_ok_tree(root: str) -> None:
    for name in ceb.ENGINE_SKILL_ALLOWLIST:
        _write(os.path.join(root, "engine", "skills", name, "SKILL.md"), "---\nname: x\n---\n")
    _write(os.path.join(root, "corpus", "skills", "cat-mode", "SKILL.md"))
    _write(os.path.join(root, "product", "skills", "diu", "SKILL.md"))
    os.makedirs(os.path.join(root, "engine", "hooks", "sample"), exist_ok=True)


class TestEcosystemBoundaries(unittest.TestCase):
    def test_ok_tree_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _minimal_ok_tree(tmp)
            self.assertEqual(ceb.check(tmp), [])

    def test_flat_skills_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            _minimal_ok_tree(tmp)
            _write(os.path.join(tmp, "skills", "sneaky", "SKILL.md"))
            errs = ceb.check(tmp)
            self.assertTrue(any("top-level skills/" in e for e in errs), errs)

    def test_engine_non_allowlist_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            _minimal_ok_tree(tmp)
            _write(os.path.join(tmp, "engine", "skills", "diu", "SKILL.md"))
            errs = ceb.check(tmp)
            self.assertTrue(any("non-allowlisted" in e for e in errs), errs)

    def test_principle_in_product_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            _minimal_ok_tree(tmp)
            _write(os.path.join(tmp, "product", "skills", "principle-foo", "SKILL.md"))
            errs = ceb.check(tmp)
            self.assertTrue(any("belong in corpus" in e for e in errs), errs)

    def test_engine_py_corpus_ref_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            _minimal_ok_tree(tmp)
            _write(
                os.path.join(tmp, "engine", "hooks", "sample", "bad.py"),
                'x = "corpus/skills/foo"\n',
            )
            errs = ceb.check(tmp)
            self.assertTrue(any("must not reference corpus/skills" in e for e in errs), errs)

    def test_domain_aware_ok_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _minimal_ok_tree(tmp)
            skill = os.path.join(tmp, "product", "skills", "judge")
            _write(
                os.path.join(skill, "SKILL.md"),
                "After reading this file, "
                + ceb.DOMAIN_SELECTOR_PHRASE
                + ":\n\n1. User named the type.\n",
            )
            _write(
                os.path.join(skill, "domains", "equities.md"),
                "Use grade_holdings_sheet.py when present.\n",
            )
            _write(
                os.path.join(skill, "domains", "coding.md"),
                "Use scripts/run_all_tests.sh when present.\n",
            )
            self.assertEqual(ceb.check(tmp), [])

    def test_domain_missing_selector_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            _minimal_ok_tree(tmp)
            skill = os.path.join(tmp, "product", "skills", "judge")
            _write(os.path.join(skill, "SKILL.md"), "No selector here.\n")
            _write(os.path.join(skill, "domains", "equities.md"), "# e\n")
            errs = ceb.check(tmp)
            self.assertTrue(any("missing selector phrase" in e for e in errs), errs)

    def test_generic_skill_names_repo_cli_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            _minimal_ok_tree(tmp)
            skill = os.path.join(tmp, "product", "skills", "judge")
            _write(
                os.path.join(skill, "SKILL.md"),
                ceb.DOMAIN_SELECTOR_PHRASE
                + "\n\nThen run grade_holdings_sheet.py\n",
            )
            _write(os.path.join(skill, "domains", "equities.md"), "# e\n")
            errs = ceb.check(tmp)
            self.assertTrue(any("must not name repo CLI" in e for e in errs), errs)

    def test_domain_file_names_other_domain_cli_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            _minimal_ok_tree(tmp)
            skill = os.path.join(tmp, "product", "skills", "judge")
            _write(
                os.path.join(skill, "SKILL.md"),
                ceb.DOMAIN_SELECTOR_PHRASE + "\n",
            )
            _write(
                os.path.join(skill, "domains", "coding.md"),
                "Do not call grade_holdings_sheet.py from coding.\n",
            )
            errs = ceb.check(tmp)
            self.assertTrue(any("equities-owned CLI" in e for e in errs), errs)


if __name__ == "__main__":
    unittest.main()
