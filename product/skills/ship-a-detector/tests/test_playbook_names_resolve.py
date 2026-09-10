#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
REPO = SKILL.parents[2]
PLAYBOOK = SKILL / "playbooks" / "detector-lifecycle.md"
sys.path.insert(0, str(REPO / "engine" / "skills" / "make-pr" / "scripts"))
import preflight  # noqa: E402

NAME_RE = re.compile(r"`([a-z][a-z0-9]*(?:-[a-z0-9]+)+)`")
NAME_HOMES = ("engine/hooks", "engine/skills", "corpus/skills", "product/skills")


def cited_names(text: str) -> set[str]:
    return set(NAME_RE.findall(text))


def unresolved(names: set[str], repo: Path) -> list[str]:
    units = {unit for _, unit in preflight.UNIT_RULES}
    return sorted(
        name for name in names
        if name not in units and not any((repo / home / name).is_dir() for home in NAME_HOMES)
    )


class TestPlaybookNamesResolve(unittest.TestCase):
    def test_every_hook_or_skill_the_playbook_cites_exists(self):
        names = cited_names(PLAYBOOK.read_text(encoding="utf-8"))
        self.assertIn("gh-write-verification", names)
        self.assertEqual(unresolved(names, REPO), [])

    def test_a_renamed_hook_is_reported_as_unresolved(self):
        names = cited_names("`diu-stop` blocked it, then `diu-stop-renamed` did too.")
        self.assertEqual(unresolved(names, REPO), ["diu-stop-renamed"])

    def test_review_units_resolve_without_a_directory(self):
        self.assertEqual(unresolved({"engine-runtime", "product-skill"}, REPO), [])


if __name__ == "__main__":
    unittest.main()
