#!/usr/bin/env python3
"""Positive + negative tests for check_skill_test_coverage."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import check_skill_test_coverage as cstc  # noqa: E402


def _write(path: Path, text: str = "# x\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _skill(root: Path, bucket: str, name: str) -> Path:
    skill_dir = root / bucket / "skills" / name
    _write(skill_dir / "SKILL.md", f"---\nname: {name}\n---\n")
    return skill_dir


class TestCodeSkills(unittest.TestCase):
    def test_code_skill_with_two_tests_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = _skill(root, "product", "demo")
            _write(skill / "scripts" / "run.py", "print('hi')\n")
            _write(
                skill / "tests" / "test_run.py",
                "def test_one():\n    assert True\n\n\ndef test_two():\n    assert True\n",
            )
            self.assertEqual(cstc.check(root, allowlist=set()), [])

    def test_code_skill_with_no_tests_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = _skill(root, "product", "demo")
            _write(skill / "scripts" / "run.py", "print('hi')\n")
            errs = cstc.check(root, allowlist=set())
            self.assertTrue(any("product/skills/demo" in e for e in errs), errs)

    def test_code_skill_with_only_one_test_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = _skill(root, "product", "demo")
            _write(skill / "scripts" / "run.py", "print('hi')\n")
            _write(skill / "tests" / "test_run.py", "def test_one():\n    assert True\n")
            errs = cstc.check(root, allowlist=set())
            self.assertTrue(any("product/skills/demo" in e for e in errs), errs)

    def test_nested_scripts_tests_dir_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = _skill(root, "engine", "demo")
            _write(skill / "scripts" / "run.py", "print('hi')\n")
            _write(
                skill / "scripts" / "tests" / "test_run.py",
                "def test_one():\n    assert True\n\n\ndef test_two():\n    assert True\n",
            )
            self.assertEqual(cstc.check(root, allowlist=set()), [])


class TestProseSkills(unittest.TestCase):
    def test_prose_skill_with_trigger_fixtures_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = _skill(root, "corpus", "demo")
            _write(skill / "tests" / "fires_example.md", "Example prompt that should fire it.\n")
            _write(skill / "tests" / "stays_silent_example.md", "Example prompt that should stay silent.\n")
            self.assertEqual(cstc.check(root, allowlist=set()), [])

    def test_prose_skill_with_no_tests_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _skill(root, "corpus", "demo")
            errs = cstc.check(root, allowlist=set())
            self.assertTrue(any("corpus/skills/demo" in e for e in errs), errs)

    def test_prose_skill_with_only_positive_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = _skill(root, "corpus", "demo")
            _write(skill / "tests" / "fires_example.md", "Should fire.\n")
            errs = cstc.check(root, allowlist=set())
            self.assertTrue(any("corpus/skills/demo" in e for e in errs), errs)


class TestAllowlist(unittest.TestCase):
    def test_allowlisted_skill_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _skill(root, "corpus", "demo")
            self.assertEqual(cstc.check(root, allowlist={"corpus/skills/demo"}), [])

    def test_list_missing_ignores_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _skill(root, "corpus", "demo")
            missing = cstc.list_missing(repo_root=root)
            self.assertIn("corpus/skills/demo", missing)

    def test_stale_allowlist_entry_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stale = cstc.stale_allowlist_entries(root, allowlist={"corpus/skills/ghost"})
            self.assertEqual(stale, ["corpus/skills/ghost"])

    def test_real_skill_not_flagged_as_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _skill(root, "corpus", "demo")
            stale = cstc.stale_allowlist_entries(root, allowlist={"corpus/skills/demo"})
            self.assertEqual(stale, [])


if __name__ == "__main__":
    unittest.main()
