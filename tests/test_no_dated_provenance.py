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
                "- **Battle-tested #2, cumulative drift without any single large payload:** a corpus.\n",
            )
            result = _run(root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_foreign_repo_qualified_tracker_refs_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "engine/hooks/demo/README.md",
                "# demo\n\nInvoker PRs #4821\u2013#4826 published cross-repo-research.\n"
                "PR #10737 (`Neko-Catpital-Labs/Invoker`) sat for two hours.\n"
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


def _run_lines(files: dict[str, str]) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for rel, line in files.items():
            _write(root / rel, f"# demo\n\n{line}\n")
        return _run(root)


SKILL = "engine/skills/demo/SKILL.md"


class TestIncidentHistoryShapes(unittest.TestCase):
    def assertFires(self, line: str, rel: str = SKILL) -> None:
        result = _run_lines({rel: line})
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(f"fail  {rel}:3", result.stdout)

    def assertSilent(self, files: dict[str, str]) -> None:
        result = _run_lines(files)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ok      no dated provenance", result.stdout)

    def test_pull_request_hash_reference_fires(self):
        self.assertFires("Invoker PR #4821 fixed the flake.")

    def test_short_published_numbers_stay_silent(self):
        self.assertSilent({SKILL: "Cook #3 and Step #12 name published principles."})

    def test_issue_hash_reference_fires(self):
        self.assertFires("Neko-Catpital-Labs/Invoker#20417 tracked the flake.")

    def test_html_entity_stays_silent(self):
        self.assertSilent({SKILL: "Write &#8212; for a dash in raw HTML."})

    def test_commit_sha_fires(self):
        self.assertFires("The regression landed in a1b2c3d and was reverted.")

    def test_hex_runs_without_both_digits_and_letters_stay_silent(self):
        self.assertSilent({SKILL: "See doi 10.1145/1064978.1065014; a defaced page is not a SHA."})

    def test_incident_opener_fires(self):
        self.assertFires("Incident: the runner sat broken for two hours.")

    def test_lowercase_incident_colon_stays_silent(self):
        self.assertSilent({SKILL: "Check for sibling passes on the same incident: `git branch --all`."})

    def test_recurred_fires(self):
        self.assertFires("This recurred three times before anyone generalized it.")

    def test_recurring_stays_silent(self):
        self.assertSilent({SKILL: "Schedule a recurring check; recurrence alone is not a bug."})

    def test_observed_on_opener_fires(self):
        self.assertFires("Observed on a self-hosted runner.")

    def test_lowercase_observed_on_stays_silent(self):
        self.assertSilent({SKILL: "Record the latency observed on the wire."})

    def test_numbered_title_exemption_covers_only_listed_titles(self):
        self.assertSilent({SKILL: 'Kimball, "Design Tip #164: Have You Built Your Audit Dimension Yet?"'})
        self.assertFires('Kimball, "Release Tip #164: Ship It"')
        self.assertFires("The flake was fixed (#4821).")

    def test_skill_trigger_example_under_tests_is_exempt_from_history_shapes(self):
        line = "User says: this bug has now recurred, see a1b2c3d and Invoker PR #4821."
        self.assertSilent({"corpus/skills/demo/tests/fires_example.md": line})
        self.assertFires(line, "corpus/skills/demo/SKILL.md")

    def test_history_shapes_stay_out_of_code_and_hook_markdown(self):
        self.assertSilent({
            "scripts/tool.py": "# Incident: reverted a1b2c3d, see #4821",
            "engine/hooks/demo/README.md": "Incident: reverted a1b2c3d, see #4821.",
        })


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


class TestGlobbedFilesAreClassified(unittest.TestCase):
    def test_nested_prose_file_is_scanned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "corpus/skills/demo/playbooks/x.md", f"# x\n\nSince {DATE} this runs.\n")
            result = _run(root)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn(f"fail  corpus/skills/demo/playbooks/x.md:3: Since {DATE}", result.stdout)

    def test_nested_code_file_is_scanned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "engine/hooks/demo/lib/x.py", f"# Since {DATE} this hook blocks.\n")
            result = _run(root)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("fail  engine/hooks/demo/lib/x.py:1", result.stdout)

    def test_always_on_file_is_scanned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "always-on/rules.md", f"# rules\n\nFound via /reflect on a {DATE} session.\n")
            result = _run(root)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("fail  always-on/rules.md:3", result.stdout)

    def test_file_outside_every_glob_stays_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "scripts/demo/tool.py", f"# Since {DATE} this runs.\n")
            _write(root / "corpus/skills/demo/playbooks/x.md", "# x\n\nAlways check disk first.\n")
            result = _run(root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("ok      no dated provenance", result.stdout)

    def test_live_tree_has_no_globbed_but_unscanned_prose(self):
        globbed = checker._matching_files(REPO, checker.PROSE_GLOBS)
        self.assertTrue(globbed, "no prose matched PROSE_GLOBS; fixture cannot run")
        unscanned = [
            p.relative_to(REPO).as_posix()
            for p in globbed
            if not checker._is_prose(p.relative_to(REPO).as_posix())
        ]
        self.assertEqual(len(unscanned), 0, unscanned)

    def test_live_tree_has_no_globbed_but_unscanned_code(self):
        globbed = checker._matching_files(REPO, checker.CODE_GLOBS)
        self.assertTrue(globbed, "no code matched CODE_GLOBS; fixture cannot run")
        unscanned = [
            p.relative_to(REPO).as_posix()
            for p in globbed
            if not checker._is_code(p.relative_to(REPO).as_posix())
        ]
        self.assertEqual(len(unscanned), 0, unscanned)

    def test_live_tree_has_no_globbed_but_unscanned_repo_ref_prose(self):
        globbed = [
            p.relative_to(REPO).as_posix()
            for p in checker._matching_files(REPO, checker.REPO_REF_GLOBS)
            if not any(d in f"/{p.relative_to(REPO).as_posix()}" for d in checker.REPO_REF_SKIP_DIRS)
        ]
        self.assertTrue(globbed, "no prose matched REPO_REF_GLOBS; fixture cannot run")
        unscanned = [rel for rel in globbed if not checker._is_repo_ref_prose(rel)]
        self.assertEqual(len(unscanned), 0, unscanned)

    def test_nested_hook_markdown_is_scanned_for_repo_refs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "engine/hooks/demo/docs/x.md", "# x\n\nSee PR #228 for the incident.\n")
            result = _run(root)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("fail  engine/hooks/demo/docs/x.md:3", result.stdout)

    def test_live_always_on_files_are_classified_as_prose(self):
        always_on = checker._matching_files(REPO, ("always-on/**/*.md",))
        self.assertTrue(always_on, "no always-on markdown found; fixture cannot run")
        for path in always_on:
            self.assertTrue(checker._is_prose(path.relative_to(REPO).as_posix()), path)


class TestLiveTreeIsCleanUnderFullScan(unittest.TestCase):
    def test_full_scan_of_this_repo_reports_no_hits(self):
        hits = checker.scan_tree(REPO)
        self.assertEqual(
            hits,
            [],
            "rule prose and hook/script code must carry no dated provenance: " + "; ".join(hits),
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

    def test_newly_added_commit_sha_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_repo_with_baseline(root, "# demo\n\nAlways check disk first.\n")
            _write(root / "corpus/skills/demo/SKILL.md", "# demo\n\nAlways check disk first.\n\nReverted in a1b2c3d.\n")
            _git(root, "add", "-A")
            _git(root, "commit", "-q", "-m", "add sha")
            result = _run_diff(root, "HEAD~1")
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("corpus/skills/demo/SKILL.md:5", result.stdout)

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
