#!/usr/bin/env python3
"""Positive + negative tests for check_skill_test_coverage."""
from __future__ import annotations

import sys
import subprocess
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


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


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


class TestChangedSkillRequiresChangedTest(unittest.TestCase):
    def test_top_level_skill_change_without_mapped_test_fails(self):
        changed = ["corpus/skills/cat-mode/SKILL.md"]
        errors = cstc.changed_skill_test_errors(changed)
        self.assertEqual(
            errors,
            [
                "corpus/skills/cat-mode: changed without a corresponding test change "
                "(expected one of: tests/test_cat_mode.py, tests/test_execution_routing.py)"
            ],
        )

    def test_git_diff_uses_merge_base_and_ignores_test_rename(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _git(root, "init", "-q", "-b", "main")
            _git(root, "config", "user.email", "test@example.com")
            _git(root, "config", "user.name", "Test")
            _skill(root, "engine", "demo")
            test_path = root / "engine/skills/demo/tests/fires_example.md"
            _write(test_path, "fires\n")
            _git(root, "add", "-A")
            _git(root, "commit", "-q", "-m", "base")
            base = _git(root, "rev-parse", "HEAD")

            _write(root / "engine/skills/demo/SKILL.md", "changed\n")
            renamed = test_path.with_name("fires_renamed_example.md")
            _git(root, "mv", str(test_path.relative_to(root)), str(renamed.relative_to(root)))
            _git(root, "add", "-A")
            _git(root, "commit", "-q", "-m", "skill plus test rename")

            changed = cstc.changed_paths_between(base, "HEAD", cwd=root)
            self.assertEqual(changed, ["engine/skills/demo/SKILL.md"])
            self.assertEqual(len(cstc.changed_skill_test_errors(changed or [])), 1)

    def test_top_level_skill_change_with_mapped_test_passes(self):
        changed = [
            "corpus/skills/cat-mode/SKILL.md",
            "tests/test_cat_mode.py",
        ]
        self.assertEqual(cstc.changed_skill_test_errors(changed), [])

    def test_colocated_skill_change_without_test_fails(self):
        changed = ["engine/skills/demo/SKILL.md"]
        errors = cstc.changed_skill_test_errors(changed)
        self.assertEqual(
            errors,
            [
                "engine/skills/demo: changed without a corresponding test change "
                "(expected a changed file under engine/skills/demo/**/tests/)"
            ],
        )

    def test_colocated_skill_change_with_test_passes(self):
        changed = [
            "engine/skills/demo/SKILL.md",
            "engine/skills/demo/tests/fires_example.md",
        ]
        self.assertEqual(cstc.changed_skill_test_errors(changed), [])

    def test_test_only_change_does_not_require_another_test(self):
        changed = ["engine/skills/demo/tests/fires_example.md"]
        self.assertEqual(cstc.changed_skill_test_errors(changed), [])

    def test_skill_script_change_also_requires_a_test_change(self):
        changed = ["engine/skills/demo/scripts/run.py"]
        errors = cstc.changed_skill_test_errors(changed)
        self.assertEqual(len(errors), 1)

    def test_each_touched_skill_requires_its_own_test_change(self):
        changed = [
            "engine/skills/alpha/SKILL.md",
            "engine/skills/alpha/tests/fires_example.md",
            "product/skills/beta/SKILL.md",
        ]
        errors = cstc.changed_skill_test_errors(changed)
        self.assertEqual(
            errors,
            [
                "product/skills/beta: changed without a corresponding test change "
                "(expected a changed file under product/skills/beta/**/tests/)"
            ],
        )


if __name__ == "__main__":
    unittest.main()
