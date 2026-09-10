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
import check_no_dated_provenance as checker  # noqa: E402
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


KIMBALL_MARKER = "Design Tip #164"
LIVE_KIMBALL_FILES = (
    "corpus/skills/principle-explicit-errors/SKILL.md",
    "corpus/skills/principle-explicit-errors/references/related-practice.md",
)


def _live_lines_containing(rel: str, marker: str) -> list[str]:
    text = (REPO / rel).read_text(encoding="utf-8")
    return [line for line in text.splitlines() if marker in line]


class TestRepoTrackerRefs(unittest.TestCase):
    def test_repo_pull_request_citation_in_hook_readme_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "engine/hooks/new-file-callout/README.md",
                "# new-file-callout\n\n"
                "The incident: a reflect subagent created `install_cursor_session_hygiene.py`\n"
                "at the catstack root inside PR #228; the parent reply listed three PR links\n"
                "and never named it.\n",
            )
            result = _run(root)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("fail  engine/hooks/new-file-callout/README.md:4", result.stdout)

    def test_live_kimball_design_tip_lines_pass_verbatim(self):
        lines: list[tuple[str, str]] = []
        for rel in LIVE_KIMBALL_FILES:
            found = _live_lines_containing(rel, KIMBALL_MARKER)
            self.assertTrue(found, f"{rel} no longer contains {KIMBALL_MARKER!r}; fixture cannot run")
            lines.extend((rel, line) for line in found)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel, line in lines:
                _write(root / rel, f"# prior art\n\n{line}\n")
            result = _run(root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_external_numbered_titles_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "corpus/CLAUDE.learned.md",
                "# rules\n\n"
                "- [Cook #3; Leveson CAST] count the defects first.\n"
                "- Richard I. Cook, *How Complex Systems Fail* \u2014 #3, \"Catastrophe requires "
                "multiple failures\".\n"
                "- **Battle-tested #2, cumulative drift without any single large payload:** a corpus.\n"
                "- a fix was planned against a branch after `origin/master` removed it (#11593).\n",
            )
            result = _run(root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_foreign_repo_qualified_tracker_refs_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "corpus/skills/demo/SKILL.md",
                "# demo\n\nInvoker PRs #10553\u2013#10558 published cross-repo-research.\n",
            )
            _write(
                root / "engine/hooks/demo/README.md",
                "# demo\n\nPR #10737 (`Neko-Catpital-Labs/Invoker`) sat for two hours.\n"
                "PR #10737 at https://github.com/Neko-Catpital-Labs/Invoker/pull/10737 had a bare body.\n"
                "Neko-Catpital-Labs/Invoker#10737 is the same one.\n",
            )
            result = _run(root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_repo_name_qualified_and_url_refs_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "corpus/skills/demo/SKILL.md", "# demo\n\ncatstack #9's always-on hook is chat only.\n")
            _write(
                root / "engine/hooks/demo/README.md",
                "# demo\n\nBorn in https://github.com/EdbertChan/catstack/pull/228 after a subagent.\n",
            )
            result = _run(root)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("corpus/skills/demo/SKILL.md:3", result.stdout)
            self.assertIn("engine/hooks/demo/README.md:3", result.stdout)

    def test_sentence_leading_word_does_not_shield_a_repo_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "corpus/skills/demo/SKILL.md", "# demo\n\nThe issue #41 that started this stays fixed.\n")
            result = _run(root)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_skill_trigger_example_under_tests_is_exempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "product/skills/land-stack/tests/fires_example.md",
                'User says: "Land PR #482, then #483 once it is merged."\n',
            )
            result = _run(root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_hook_markdown_stays_outside_the_date_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "engine/hooks/demo/README.md", f"# demo\n\nBorn from a `/reflect` on a {DATE} session.\n")
            result = _run(root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_reference_subdirectory_prose_is_in_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "corpus/skills/demo/references/notes.md", "# notes\n\nSee PR #228 for the incident.\n")
            result = _run(root)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("corpus/skills/demo/references/notes.md:3", result.stdout)


class TestLiveTreeCitesNoRepoTracker(unittest.TestCase):
    def test_no_live_rule_prose_cites_this_repo_issues_or_pull_requests(self):
        scanned = checker._matching_files(REPO, checker.REPO_REF_GLOBS)
        scanned += [REPO / rel for rel in checker.PROSE_FILES if (REPO / rel).is_file()]
        offenders = []
        for path in sorted(set(scanned)):
            rel = path.relative_to(REPO).as_posix()
            if not checker._is_repo_ref_prose(rel):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(text.splitlines(), 1):
                if checker._cites_repo_tracker(line):
                    offenders.append(f"{rel}:{lineno}: {line.strip()}")
        self.assertEqual(
            offenders,
            [],
            "rule prose must state the rule, not where the repo learned it: " + "; ".join(offenders),
        )


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

    def test_newly_added_repo_pull_request_ref_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_repo_with_baseline(root, "# demo\n\nAlways check disk first.\n")
            _write(root / "corpus/skills/demo/SKILL.md", "# demo\n\nAlways check disk first.\n\nBorn inside PR #228.\n")
            _git(root, "add", "-A")
            _git(root, "commit", "-q", "-m", "add repo ref")
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
