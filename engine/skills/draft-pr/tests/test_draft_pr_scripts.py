#!/usr/bin/env python3
"""Positive + negative tests for engine/skills/draft-pr's scripts/validate-pr-body.mjs.

These shell out to the real Node script against @neko-catpital-labs/drafter-core
(a committed devDependency -- see package.json) rather than reimplementing
its schema logic in Python, since the wrapper script IS the thing being
tested: does it actually accept a well-formed PR body and reject a
malformed one, end to end.
"""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "engine" / "skills" / "draft-pr" / "scripts" / "validate-pr-body.mjs"

VALID_BODY = """## Summary

Fixes a bug where the widget renderer crashed on empty input.

## Review Claim

Approve the null-check fix for the widget renderer.

## Review Lane

behavior

## Review Unit

product

## Safety Invariant

Only adds a guard clause; existing non-empty-input behavior is unchanged.

## Slice Rationale

Small, isolated bug fix -- no reason to bundle with anything else.

## Non-goals

- Does not refactor the renderer.

## Test Plan

<details>
<summary>Test Plan</summary>

- [x] `pytest tests/test_widget_renderer.py`

</details>

## Revert Plan

<details>
<summary>Revert Plan</summary>

- Safe to revert? Yes
- Revert command: `git revert <sha>`
- Post-revert steps: None
- Data migration? No

</details>
"""

# A review unit value that isn't in the configured taxonomy at all --
# the same mistake this repo's own PR stack made in practice with
# "engine-runtime" before drafter.config.json existed. Deliberately not
# "engine-runtime" itself: that string is now a real configured unit
# (see drafter.config.json), so it would no longer be invalid here.
INVALID_BODY = VALID_BODY.replace(
    "## Review Unit\n\nproduct", "## Review Unit\n\ntotally-bogus-unit-xyz"
)

VALID_SUMMARY = "Fixes a bug where the widget renderer crashed on empty input."

HARD_SUMMARY = """Bare repository references such as `(#322)` now fail the existing provenance gate. Rule text should explain requirements and consequences; commit messages retain repository history.

The detector lifecycle playbook and owning skill lose local PR citations while retaining their instructions. An external Invoker reference gains an explicit project name.

Regression tests cover rejected references, preserved external citations, and resolvable playbook names. A skill-usage-log test now checks its temporary state directory."""

PLAIN_SUMMARY = """Rule files in this repo can no longer point at old PRs with a bare number like "#322". A test now fails if they do.

"See #322" only tells a reader where to dig. Each rule should say what to do and why, in its own words.

This PR also rewrites the old PR numbers in the detector playbook, so each rule there explains itself.

Numbers that name outside work, like "Cook #3", still pass."""


def _with_summary(summary: str) -> str:
    return VALID_BODY.replace(VALID_SUMMARY, summary)


ENGINE_BODY = VALID_BODY.replace("## Review Unit\n\nproduct", "## Review Unit\n\nengine-runtime")

BEFORE_SUMMARY = (
    "When diu-stop or prove-it-ship-gate block a reply and the agent rewrites it, "
    "the rewrite is still checked for evidence. Before, both hooks returned on "
    "`stop_hook_active` before running any check."
)

AFTER_SUMMARY = (
    "Before Claude sends a reply, small checker scripts read it. One checks length. "
    "Others check that every claim comes with proof. If a check fails, Claude must "
    "rewrite. The problem: when Claude rewrote, both checkers stepped aside completely."
)

HOOK_FILES = [
    "engine/hooks/diu-stop/claude_stop_check.py",
    "engine/hooks/prove-it-ship-gate/detect.py",
]

CODE_NAME_ERROR = "Summary and Review Claim must not use code names"


def _run_validator(body_text: str, changed_files: list[str] | None = None) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as tmp:
        body_file = Path(tmp) / "body.md"
        body_file.write_text(body_text, encoding="utf-8")
        extra = []
        if changed_files is not None:
            files = Path(tmp) / "files.txt"
            files.write_text("\n".join(changed_files) + "\n", encoding="utf-8")
            extra = ["--changed-files-file", str(files)]
        return subprocess.run(
            ["node", str(SCRIPT), "--body-file", str(body_file), *extra],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )


class TestValidatePrBody(unittest.TestCase):
    def test_well_formed_body_passes(self):
        result = _run_validator(VALID_BODY)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("PR body validation passed", result.stdout)

    def test_invalid_review_unit_fails_closed(self):
        result = _run_validator(INVALID_BODY)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("Invalid review unit", result.stderr)

    def test_hook_with_its_ecosystem_inventory_row_passes(self):
        """A hook and its docs/ecosystem.md row land together (ship-a-detector step 17)."""
        result = _run_validator(ENGINE_BODY, ["engine/hooks/demo/detect.py", "docs/ecosystem.md"])
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_hook_with_other_docs_still_fails(self):
        result = _run_validator(ENGINE_BODY, ["engine/hooks/demo/detect.py", "docs/guide.md"])
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("cannot ship with docs files", result.stderr)


class TestSummaryReadingGrade(unittest.TestCase):
    def test_hard_summary_is_blocked(self):
        result = _run_validator(_with_summary(HARD_SUMMARY))
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("Summary is too hard to read", result.stderr)
        self.assertIn("grade 12.9", result.stderr)

    def test_plain_summary_passes(self):
        result = _run_validator(_with_summary(PLAIN_SUMMARY))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertNotIn("too hard to read", result.stderr)

    def test_short_summary_is_reported_unchecked_not_passed(self):
        result = _run_validator(VALID_BODY)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("reading grade unchecked", result.stderr)

    def test_code_spans_do_not_count_as_long_words(self):
        """Code spans fail the code-name check, not the reading grade."""
        spans = " ".join(f"`engine/skills/draft-pr/scripts/validate_{i}.mjs`" for i in range(12))
        summary = PLAIN_SUMMARY + f"\n\nThe files are {spans}."
        result = _run_validator(_with_summary(summary))
        self.assertNotIn("too hard to read", result.stderr)
        self.assertIn(CODE_NAME_ERROR, result.stderr)



class TestSummaryCodeNames(unittest.TestCase):
    def _engine_body(self, summary: str) -> str:
        return ENGINE_BODY.replace(VALID_SUMMARY, summary)

    def test_code_names_in_summary_fail_and_are_each_named(self):
        result = _run_validator(self._engine_body(BEFORE_SUMMARY), HOOK_FILES)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(CODE_NAME_ERROR, result.stderr)
        for name in ("stop_hook_active", "diu-stop", "prove-it-ship-gate"):
            self.assertIn(f'"{name}"', result.stderr)
        self.assertIn("put the name in a later section such as Test Plan", result.stderr)

    def test_plain_summary_passes_with_the_same_changed_files(self):
        result = _run_validator(self._engine_body(AFTER_SUMMARY), HOOK_FILES)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertNotIn(CODE_NAME_ERROR, result.stderr)

    def test_hyphenated_english_words_are_not_code_names(self):
        summary = (
            "This adds a brand-new word-count limit to the form. A person who types "
            "too much now sees a short note that says how many words to cut."
        )
        result = _run_validator(_with_summary(summary))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertNotIn(CODE_NAME_ERROR, result.stderr)

    def test_missing_summary_is_reported_unchecked_not_clean(self):
        body = VALID_BODY.replace(f"## Summary\n\n{VALID_SUMMARY}\n\n", "")
        self.assertNotIn("## Summary", body)
        result = _run_validator(body)
        self.assertIn("Code-name check unchecked: no ## Summary section to read", result.stderr)

    def test_code_names_in_later_sections_do_not_fail(self):
        body = self._engine_body(AFTER_SUMMARY).replace(
            "- [x] `pytest tests/test_widget_renderer.py`",
            "- [x] `python3 engine/hooks/diu-stop/claude_stop_check.py` exits 0 once "
            "`stop_hook_active` is set; prove-it-ship-gate/detect.py too",
        ).replace(
            "- Post-revert steps: None",
            "- Post-revert steps: diu-stop and prove-it-ship-gate return on `stop_hook_active` again",
        ).replace(
            "## Test Plan",
            """## Architecture

diu-stop and prove-it-ship-gate both read `stop_hook_active`.

### Before

```mermaid
graph TD
    A["claude_stop_check.py"] --> B["return on stop_hook_active"]
```

### After

diu-stop/claude_stop_check.py keeps checking; detect.py too.

```mermaid
graph TD
    A["claude_stop_check.py"] --> B["run every check"]
```

## Test Plan""",
        )
        result = _run_validator(body, HOOK_FILES)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertNotIn(CODE_NAME_ERROR, result.stderr)
        self.assertNotIn("Code-name check unchecked", result.stderr)


if __name__ == "__main__":
    unittest.main()
