#!/usr/bin/env python3
"""Positive + negative tests for check_no_dated_provenance."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "check_no_dated_provenance.py"
sys.path.insert(0, str(REPO / "scripts"))

from git_test_repo import init_repo  # noqa: E402
DATE = "2026-09-01"  # kept apart from the keyword so this file never self-flags


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _run(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(root)], capture_output=True, text=True
    )


class TestNoDatedProvenance(unittest.TestCase):
    def test_dated_since_note_in_skill_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "engine/skills/demo/SKILL.md", f"# demo\n\nSince {DATE} this gate is on.\n")
            result = _run(root)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn(f"fail  engine/skills/demo/SKILL.md:3: Since {DATE}", result.stdout)

    def test_found_via_citation_in_skill_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "corpus/skills/demo/SKILL.md",
                f"# demo\n\nFound via /reflect on a {DATE} session: the thing.\n",
            )
            result = _run(root)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("fail  corpus/skills/demo/SKILL.md:3", result.stdout)

    def test_bare_date_with_no_provenance_keyword_in_skill_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "corpus/skills/demo/SKILL.md",
                f"# demo\n\nThe user asked for this on {DATE} and it stuck.\n",
            )
            result = _run(root)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_dated_fixture_and_undated_rule_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "corpus/skills/demo/SKILL.md", "# demo\n\nAlways check disk before calling a skill unavailable.\n")
            _write(root / f"engine/skills/demo/tests/fixtures/added-{DATE}.md", f"Added {DATE}\n")
            _write(root / "scripts/tool.py", f"# a fixture constant, not provenance: {DATE}\n")
            result = _run(root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("ok      no dated provenance", result.stdout)


class TestNestedPathsAreScanned(unittest.TestCase):
    def test_nested_prose_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "corpus/skills/demo/playbooks/x.md",
                f"# x\n\nFound via /reflect on a {DATE} session: the thing.\n",
            )
            result = _run(root)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("fail  corpus/skills/demo/playbooks/x.md:3", result.stdout)

    def test_deeply_nested_prose_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "product/skills/demo/playbooks/deep/deeper/y.md",
                f"# y\n\nSince {DATE} this gate is on.\n",
            )
            result = _run(root)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("fail  product/skills/demo/playbooks/deep/deeper/y.md:3", result.stdout)

    def test_nested_code_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "engine/hooks/demo/lib/helper.py",
                f"def run():\n    return 1  # Since {DATE} this returns 1\n",
            )
            result = _run(root)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("fail  engine/hooks/demo/lib/helper.py:2", result.stdout)

    def test_always_on_file_at_glob_root_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "always-on/evidence-check.md", f"# rules\n\nAdded {DATE} by reflect.\n")
            result = _run(root)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("fail  always-on/evidence-check.md:3", result.stdout)

    def test_nested_always_on_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "always-on/packs/extra.md", f"# rules\n\nAdded {DATE} by reflect.\n")
            result = _run(root)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("fail  always-on/packs/extra.md:3", result.stdout)

    def test_nested_clean_and_out_of_scope_dated_files_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "corpus/skills/demo/playbooks/x.md", "# x\n\nCheck disk before calling a skill unavailable.\n")
            _write(root / "engine/hooks/demo/lib/helper.py", "def run():\n    return 1\n")
            _write(root / "always-on/evidence-check.md", "# rules\n\nShow the command and its output.\n")
            _write(root / "docs/notes/journal.md", f"Found via /reflect on a {DATE} session.\n")
            _write(root / "corpus/skills/demo/tests/fixtures/dated.md", f"Since {DATE}\n")
            result = _run(root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("ok      no dated provenance", result.stdout)

    def test_every_globbed_file_in_this_repo_is_classified(self):
        sys.path.insert(0, str(REPO / "scripts"))
        import check_no_dated_provenance as gate

        unscanned = [
            p.relative_to(gate.REPO).as_posix()
            for p in gate._matching_files(gate.REPO, gate.PROSE_GLOBS)
            if not gate._is_prose(p.relative_to(gate.REPO).as_posix())
        ]
        self.assertEqual(unscanned, [], f"globbed but unscanned: {len(unscanned)}")

        unscanned_code = [
            p.relative_to(gate.REPO).as_posix()
            for p in gate._matching_files(gate.REPO, gate.CODE_GLOBS)
            if not gate._is_code(p.relative_to(gate.REPO).as_posix())
        ]
        self.assertEqual(unscanned_code, [], f"globbed but unscanned: {len(unscanned_code)}")

    def test_glob_matcher_agrees_with_pathlib_glob(self):
        sys.path.insert(0, str(REPO / "scripts"))
        import check_no_dated_provenance as gate

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in (
                "engine/skills/a.md",
                "engine/skills/demo/SKILL.md",
                "engine/skills/demo/playbooks/deep/x.md",
                "corpus/skills/demo/playbooks/x.md",
                "product/skills/demo/x.md",
                "always-on/x.md",
                "always-on/packs/x.md",
                "commands/x.md",
                "cursor/rules/x.mdc",
                "engine/hooks/demo/lib/helper.py",
                "scripts/tool.py",
                "scripts/nested/tool.py",
                "tests/test_x.py",
                "tests/nested/test_x.py",
                "docs/x.md",
            ):
                _write(root / rel, "x\n")

            for patterns, predicate in (
                (gate.PROSE_GLOBS, gate._is_prose),
                (gate.CODE_GLOBS, gate._is_code),
            ):
                globbed = {p.relative_to(root).as_posix() for p in gate._matching_files(root, patterns)}
                for path in root.rglob("*"):
                    if not path.is_file():
                        continue
                    rel = path.relative_to(root).as_posix()
                    self.assertEqual(predicate(rel), rel in globbed, rel)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True,
        env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin"},
    )


def _run_diff(root: Path, base: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--base", base], capture_output=True, text=True, cwd=str(root)
    )


class TestNoDatedProvenanceDiffAware(unittest.TestCase):
    def _init_repo_with_baseline(self, root: Path, baseline_text: str) -> None:
        init_repo(root)
        _write(root / "corpus/skills/demo/SKILL.md", baseline_text)
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "baseline")

    def test_newly_added_dated_line_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_repo_with_baseline(root, "# demo\n\nAlways check disk first.\n")
            _write(root / "corpus/skills/demo/SKILL.md", f"# demo\n\nAlways check disk first.\n\nFound via /reflect on a {DATE} session.\n")
            _git(root, "add", "-A")
            _git(root, "commit", "-q", "-m", "add violation")
            result = _run_diff(root, "HEAD~1")
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("corpus/skills/demo/SKILL.md", result.stdout)

    def test_preexisting_dated_line_untouched_by_diff_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_repo_with_baseline(root, f"# demo\n\nFound via /reflect on a {DATE} session, already here.\n")
            _write(root / "corpus/skills/demo/SKILL.md", f"# demo\n\nFound via /reflect on a {DATE} session, already here.\n\nA new, unrelated, dateless bullet.\n")
            _git(root, "add", "-A")
            _git(root, "commit", "-q", "-m", "unrelated addition")
            result = _run_diff(root, "HEAD~1")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("ok      no dated provenance", result.stdout)


if __name__ == "__main__":
    unittest.main()
