## Summary

Spreadsheet charts now require a clear measurement contract before data is aggregated or compared.

The prior workflow could build a competitor chart before defining the metric, denominator, geography, cadence, or comparison set.

The skill now requires those choices and derives the chart’s explanatory text from them.

## Review Claim

Approve the measurement-contract rule for comparable spreadsheet tables and charts.

## Review Lane

policy

## Review Unit

product-skill

## Safety Invariant

The rule changes authoring requirements only; it does not alter existing workbooks or infer a metric when the contract is incomplete.

## Slice Rationale

This is a focused skill slice that records the required contract before future aggregation and chart work.

## Non-goals

- Does not change the live Google Sheet.
- Does not choose the Rideshare metric or competitor inventory.
- Does not add the separate mechanical chart-contract validator.

## Test Plan

<details>
<summary>Test Plan</summary>

- `git diff --check`
- `python3 scripts/ci/check_skill_test_coverage.py --base origin/main --head HEAD`
- `python3 scripts/ci/check_skills_three_harnesses.py`
- `python3 scripts/ci/check_ecosystem_boundaries.py`

</details>

## Revert Plan

<details>
<summary>Revert Plan</summary>

- Safe to revert? Yes.
- Revert command: `git revert <sha>`.
- Post-revert steps: None.
- Data migration? No.

</details>
