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


if __name__ == "__main__":
    unittest.main()
