## Summary

Charts now explain every plotted encoding inside the graph itself.

The prior workflow could treat a nearby sheet key as sufficient, leaving the graph ambiguous.

The fix adds a reusable chart-spec check and documents the native legend contract.

## Review Claim

Approve the chart contract that requires native semantic legends and rejects external key substitutes.

## Review Lane

behavior

## Review Unit

product-skill

## Safety Invariant

A chart cannot pass validation unless its native legend is enabled, its source includes a header row, and every plotted series has a distinct semantic label.

## Slice Rationale

This is one product-skill slice: the validator and its fixtures enforce the rule documented by the spreadsheet-authoring skill.

## Non-goals

- Does not change live Google Sheets files.
- Does not change chart colors, chart layout, or aggregation formulas.
- Does not infer labels from company names when the series role is missing.

## Test Plan

<details>
<summary>Test Plan</summary>

- `python3 -m unittest discover -s product/skills/spreadsheet-authoring/tests -p 'test_*.py' -v`
- `python3 scripts/ci/check_skill_test_coverage.py --base origin/main --head HEAD`
- `python3 scripts/ci/check_skills_three_harnesses.py`
- `python3 scripts/ci/check_ecosystem_boundaries.py`
- `git diff --check`

</details>

## Revert Plan

<details>
<summary>Revert Plan</summary>

- Safe to revert? Yes.
- Revert command: `git revert <sha>`.
- Post-revert steps: None.
- Data migration? No.

</details>
