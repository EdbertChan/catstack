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


PR_NUM = "#" + "4821"
ISSUE_NUM = "#" + "731"
SHA = "b7e21f9"


class TestWidenedProseShapes(unittest.TestCase):
    def _prose(self, body: str) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "corpus/skills/demo/SKILL.md", f"# demo\n\n{body}\n")
            return _run(root)

    def _assert_fires(self, body: str) -> None:
        result = self._prose(body)
        self.assertEqual(result.returncode, 1, f"expected a hit for {body!r}\n{result.stdout}")
        self.assertIn("fail  corpus/skills/demo/SKILL.md:3", result.stdout)

    def _assert_silent(self, body: str) -> None:
        result = self._prose(body)
        self.assertEqual(result.returncode, 0, f"false positive on {body!r}\n{result.stdout}")
        self.assertIn("ok      no dated provenance", result.stdout)

    def test_pr_reference_fires(self):
        self._assert_fires(f"Reverted in PR {PR_NUM} after the gate flagged it.")

    def test_pr_shaped_colour_and_counts_stay_silent(self):
        self._assert_silent("Set the swatch to #1a2b3c and cap the run at 4096 rows.")

    def test_issue_reference_fires(self):
        self._assert_fires(f"Filed as issue {ISSUE_NUM} and closed the same week.")

    def test_markdown_heading_with_digits_stays_silent(self):
        self._assert_silent("##### 404 handling belongs in the router, not the view.")

    def test_bare_commit_sha_fires(self):
        self._assert_fires(f"The fix landed as {SHA} on the release branch.")

    def test_doi_digits_stay_silent(self):
        self._assert_silent("Source: <https://doi.org/10.1145/2468013.2468024>.")

    def test_hex_looking_word_without_digits_stays_silent(self):
        self._assert_silent("The deadbeef placeholder is prose, not a hash.")

    def test_incident_opener_fires(self):
        self._assert_fires("Incident: the gate sat broken while the queue drained.")

    def test_lowercase_incident_noun_stays_silent(self):
        self._assert_silent("Check for sibling passes on the same incident: run the query.")

    def test_recurred_fires(self):
        self._assert_fires("The registration bug recurred three times across separate fixes.")

    def test_recurrence_noun_stays_silent(self):
        self._assert_silent("Recurrence is the trigger; state the shape, not the count.")

    def test_observed_on_fires(self):
        self._assert_fires("Observed on a self-hosted runner during the nightly sweep.")

    def test_observed_behaviour_stays_silent(self):
        self._assert_silent("Observed behaviour is the contract; say what the reader sees.")

    def test_widened_shapes_do_not_fire_on_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "scripts/tool.py",
                f"VALUES = ({PR_NUM!r}, {SHA!r})\nLABEL = 'Observed on the runner; it recurred.'\n",
            )
            result = _run(root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class TestWidenedShapeExemptions(unittest.TestCase):
    def test_skill_test_fixture_prose_is_exempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = (
                f"Incident: PR {PR_NUM} and issue {ISSUE_NUM} broke at {SHA}.\n"
                "Observed on the runner, and it recurred.\n"
            )
            _write(root / "product/skills/demo/tests/fires_example.md", body)
            _write(root / "product/skills/demo/tests/stays_silent_example.md", body)
            result = _run(root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_same_text_outside_the_fixture_dir_still_fires(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "product/skills/demo/SKILL.md", f"# demo\n\nObserved on {SHA}.\n")
            result = _run(root)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_repo_own_python_tests_are_not_exempted_by_the_tests_dir_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "tests/test_thing.py", f"LABEL = 'Since {DATE} this is on'\n")
            result = _run(root)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("fail  tests/test_thing.py:1", result.stdout)

    def test_reference_inside_a_quoted_title_is_exempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "corpus/skills/demo/SKILL.md",
                f'# demo\n\nSource: Kimball, "Design Tip {ISSUE_NUM}: Build Your Audit\n',
            )
            result = _run(root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_reference_before_an_opening_quote_still_fires(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "corpus/skills/demo/SKILL.md",
                f'# demo\n\n{PR_NUM} opens with: "Two shipped hooks never ran.\n',
            )
            result = _run(root)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_reference_after_a_closing_quote_still_fires(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "corpus/skills/demo/SKILL.md",
                f'# demo\n\npassing negative fixture." {PR_NUM} added an allowlist.\n',
            )
            result = _run(root)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_fenced_illustration_block_is_exempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "corpus/skills/demo/SKILL.md",
                f"# demo\n\nIllustration only:\n\n```\nevidence\tcommit {SHA}\tresult\n```\n",
            )
            result = _run(root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_the_same_line_after_the_fence_closes_fires(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "corpus/skills/demo/SKILL.md",
                f"# demo\n\n```\nsample\n```\n\nThe fix landed as {SHA}.\n",
            )
            result = _run(root)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("fail  corpus/skills/demo/SKILL.md:7", result.stdout)

    def test_dates_and_found_via_are_not_exempted_by_fence_or_quote(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "corpus/skills/fenced/SKILL.md",
                f"# demo\n\n```\nSince {DATE} this gate is on.\n```\n",
            )
            _write(
                root / "corpus/skills/quoted/SKILL.md",
                f'# demo\n\nHe said: "Found via /reflect on a {DATE} session."\n',
            )
            result = _run(root)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("fail  corpus/skills/fenced/SKILL.md:4", result.stdout)
            self.assertIn("fail  corpus/skills/quoted/SKILL.md:3", result.stdout)


class TestUnreadableFenceStateFailsClosed(unittest.TestCase):
    def test_missing_file_yields_no_fence_exemption(self):
        import check_no_dated_provenance as gate

        gate._worktree_fence_flags.cache_clear()
        self.assertEqual(gate._worktree_fence_flags("no/such/file.md"), ())
        self.assertFalse(gate._worktree_fence("no/such/file.md", 3))

    def test_line_is_still_checked_when_fence_state_is_unavailable(self):
        import check_no_dated_provenance as gate

        gate._worktree_fence_flags.cache_clear()
        in_fence = gate._worktree_fence("no/such/file.md", 3)
        self.assertTrue(
            gate._line_violates("corpus/skills/demo/SKILL.md", f"The fix landed as {SHA}.", in_fence)
        )

    def test_line_beyond_end_of_file_yields_no_fence_exemption(self):
        import check_no_dated_provenance as gate

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "short.md"
            _write(target, "one line\n")
            gate._worktree_fence_flags.cache_clear()
            self.assertFalse(gate._worktree_fence(str(target), 99))


class TestShaBoundaries(unittest.TestCase):
    def _fires(self, body: str) -> bool:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "corpus/skills/demo/SKILL.md", f"# demo\n\n{body}\n")
            return _run(root).returncode == 1

    def test_six_hex_chars_is_too_short(self):
        self.assertFalse(self._fires("The token b7e21f is shorter than a short SHA."))

    def test_more_than_forty_hex_chars_is_not_a_sha(self):
        self.assertFalse(self._fires("Payload " + ("b7e21f9" * 7) + " is not a SHA."))

    def test_forty_hex_chars_is_a_sha(self):
        self.assertTrue(self._fires("The fix landed as " + ("b7e21f9" * 5 + "abcd1") + "."))

    def test_sha_at_end_of_sentence_fires(self):
        self.assertTrue(self._fires(f"The fix landed as {SHA}."))


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

    def test_unqualified_bare_number_in_rule_text_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "corpus/CLAUDE.learned.md",
                "# rules\n\n- a fix was planned against a branch after `origin/master` removed it (#11593).\n",
            )
            result = _run(root)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("fail  corpus/CLAUDE.learned.md:3", result.stdout)

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


    def test_newly_added_pr_reference_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_repo_with_baseline(root, "# demo\n\nAlways check disk first.\n")
            _write(
                root / "corpus/skills/demo/SKILL.md",
                f"# demo\n\nAlways check disk first.\n\nReverted in PR {PR_NUM} after the gate flagged it.\n",
            )
            _git(root, "add", "-A")
            _git(root, "commit", "-q", "-m", "add reference")
            result = _run_diff(root, "HEAD~1")
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("corpus/skills/demo/SKILL.md:5", result.stdout)

    def test_newly_added_narrative_opener_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_repo_with_baseline(root, "# demo\n\nAlways check disk first.\n")
            _write(
                root / "corpus/skills/demo/SKILL.md",
                "# demo\n\nAlways check disk first.\n\nObserved on a self-hosted runner; it recurred.\n",
            )
            _git(root, "add", "-A")
            _git(root, "commit", "-q", "-m", "add narrative")
            result = _run_diff(root, "HEAD~1")
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_newly_added_line_inside_a_fence_is_exempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_repo_with_baseline(root, "# demo\n\nIllustration only:\n\n```\nsample\n```\n")
            _write(
                root / "corpus/skills/demo/SKILL.md",
                f"# demo\n\nIllustration only:\n\n```\nsample\nevidence\tcommit {SHA}\tresult\n```\n",
            )
            _git(root, "add", "-A")
            _git(root, "commit", "-q", "-m", "add sample row")
            result = _run_diff(root, "HEAD~1")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("ok      no dated provenance", result.stdout)

    def test_newly_added_line_after_the_fence_closes_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_repo_with_baseline(root, "# demo\n\n```\nsample\n```\n")
            _write(
                root / "corpus/skills/demo/SKILL.md",
                f"# demo\n\n```\nsample\n```\n\nThe fix landed as {SHA}.\n",
            )
            _git(root, "add", "-A")
            _git(root, "commit", "-q", "-m", "add trailer")
            result = _run_diff(root, "HEAD~1")
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("corpus/skills/demo/SKILL.md:7", result.stdout)

    def test_newly_added_skill_fixture_prose_is_exempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_repo_with_baseline(root, "# demo\n\nAlways check disk first.\n")
            _write(
                root / "corpus/skills/demo/tests/fires_example.md",
                f"User says: \"Land PR {PR_NUM}, then {ISSUE_NUM} once it's merged.\"\n",
            )
            _git(root, "add", "-A")
            _git(root, "commit", "-q", "-m", "add fixture")
            result = _run_diff(root, "HEAD~1")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
