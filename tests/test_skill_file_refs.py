#!/usr/bin/env python3
"""Positive + negative tests for check_skill_file_refs."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import check_skill_file_refs as csf  # noqa: E402


def _write(path: Path, text: str = "# x\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _skill(root: Path, bucket: str, name: str, skill_md: str) -> Path:
    skill_dir = root / bucket / "skills" / name
    _write(skill_dir / "SKILL.md", skill_md)
    return skill_dir


class TestSkillFileRefs(unittest.TestCase):
    def test_existing_repo_path_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "scripts" / "run_all_tests.sh", "#!/bin/bash\n")
            _skill(
                root,
                "product",
                "demo",
                "Run `scripts/run_all_tests.sh`.\n",
            )
            self.assertEqual(csf.check(root), [])

    def test_existing_skill_local_path_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = _skill(root, "product", "demo", "See `references/fixture.json`.\n")
            _write(skill / "references" / "fixture.json", "{}\n")
            self.assertEqual(csf.check(root), [])

    def test_missing_repo_path_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _skill(
                root,
                "product",
                "demo",
                "Call `scripts/does_not_exist.py`.\n",
            )
            errs = csf.check(root)
            self.assertTrue(any("does_not_exist.py" in e for e in errs), errs)

    def test_slash_command_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _skill(root, "product", "demo", "Use `/reflect` then `/loop`.\n")
            self.assertEqual(csf.check(root), [])

    def test_consumer_allowlist_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _skill(
                root,
                "product",
                "demo",
                "Load `.cursor/judge-swarm-bindings.json` from cwd.\n",
            )
            self.assertEqual(csf.check(root), [])

    def test_legacy_skills_prefix_resolves(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _skill(root, "product", "diu", "---\nname: diu\n---\n")
            _skill(
                root,
                "product",
                "adhd",
                "See `skills/diu/SKILL.md`.\n",
            )
            self.assertEqual(csf.check(root), [])

    def test_home_path_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _skill(root, "engine", "reflect", "Read `~/.claude/projects/`.\n")
            self.assertEqual(csf.check(root), [])


if __name__ == "__main__":
    unittest.main()
