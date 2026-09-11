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

PLAIN_SUMMARY = """Rule files in this repo can no longer point at old PRs with a bare number like `#322`. A test now fails if they do.

"See `#322`" only tells a reader where to dig. Each rule should say what to do and why, in its own words.

This PR also rewrites the old PR numbers in the detector playbook, so each rule there explains itself.

Numbers that name outside work, like "Cook `#3`", still pass."""


def _with_summary(summary: str) -> str:
    return VALID_BODY.replace(VALID_SUMMARY, summary)


def _run_validator(body_text: str) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as tmp:
        body_file = Path(tmp) / "body.md"
        body_file.write_text(body_text, encoding="utf-8")
        return subprocess.run(
            ["node", str(SCRIPT), "--body-file", str(body_file)],
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
        spans = " ".join(f"`engine/skills/draft-pr/scripts/validate_{i}.mjs`" for i in range(12))
        summary = PLAIN_SUMMARY + f"\n\nThe files are {spans}."
        result = _run_validator(_with_summary(summary))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
