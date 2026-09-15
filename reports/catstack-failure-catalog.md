# Catstack failure catalog — first pass

## Scope

This report covers failures recorded in the current Catstack design and gap
documents, the three metrics repros from `3ef9afa`, and the merge-gate branch
incident `wf-1789406765789-20`. It does not claim coverage of private chat,
unlogged workstation failures, or external systems without a local record.

## Directly evidenced failures

| ID | Failure | Root cause | Evidence |
| --- | --- | --- | --- |
| F01 | A Cursor allow reply is counted as `spoke`. | The runner treats any non-empty output as speech instead of interpreting `continue: true` as silent allow. | `engine/hooks/_runner/outcome.py:36-49`; direct assertion: `AssertionError: expected silent, got 'spoke'`. |
| F02 | Metrics rows omit the rule that fired. | `_row()` has no finding identity or `rule_id` input and does not emit that field. | `engine/hooks/_runner/run.py:71-95`; direct assertion: `AssertionError: row has no rule_id`. |
| F03 | A drained judge verdict never becomes a metrics row. | `judge.drain()` returns verdicts and deletes claimed files, but no metrics writer consumes them. | `engine/hooks/llm-judge/judge.py:254-286`; direct assertion: `AssertionError: []`. |
| F04 | A merge-gate base branch disappeared after its PR merged. | GitHub had `delete_branch_on_merge=true`; PR #612 merged with this branch as its head. | GitHub API; PR #612; fresh `git ls-remote` returned no ref. |
| F05 | Invoker retried a missing base branch. | Base synchronization was skipped as `origin-refs-fresh`, then resolution used a no-fetch lookup; managed-branch cleanup was disabled. | `/Users/edbertchan/.invoker/invoker.log:4178210-4178225`. |

The first three repro commands exited `1` with the failure lines above. F04
was a live remote-state check; F05 was a live execution trace, not a unit
test. No product fix was made while collecting this report.

## Documented candidates needing independent probes

| ID | Candidate failure | Recorded explanation |
| --- | --- | --- |
| C01 | Each hook chooses stop versus warn independently. | No central mode field exists. |
| C02 | Hook output shapes differ across harnesses. | Many harness-specific output forms are implemented directly. |
| C03 | There is no central hook list. | Hook fragments and installer lists are duplicated. |
| C04 | Metrics infer meaning from output. | The runner classifies raw process output. |
| C05 | Metrics lack follow-up outcome data. | Acted, ignored, and override events are not recorded. |
| C06 | Metrics logs have no rotation. | The runner appends to `runs.jsonl` without retention. |
| C07 | Helpers are copied across hooks. | Transcript, session, and judge-loading logic has multiple copies. |
| C08 | Installed hooks drift from upstream. | The gap analysis records stale and deleted hooks still installed. |
| C09 | Agents can invent values after a prohibition. | A generic hook cannot compare reply values with product data. |
| C10 | Agents can claim done without proof. | A reply-level evidence gate was missing. |
| C11 | Agents repeat named constraints. | No detector recognized repeated user constraints. |
| C12 | Proof requests are repeated because evidence is missing. | No shared proof-evidence gate existed. |
| C13 | Hook feedback is counted as human input. | Feedback lines were not excluded from the watchdog input. |
| C14 | The brevity hook blocks analysis replies. | The configured word cap applies to research answers; the record calls this tuning. |
| C15 | Mined principles can lack transcript grounding. | Grounding requires review evidence. |
| C16 | Workflow prompt resends look like audit failures. | Template resends are counted as verbatim repeats. |
| C17 | A stale merge-gate base is not rejected at submission. | The workflow persists a branch name without a live remote-ref guard. |

Sources: `docs/hook-architecture.md:13-27` and
`docs/hooks-gap-analysis.md:17-28`. “Candidate” means documented here but not
independently reprobed in this pass; it is not a clean result.

## Root-cause grouping

The directly evidenced failures group into two independent seams:

1. Typed outcome data is lost between detectors, judge results, and metrics
   rows (F01–F03).
2. Remote branch lifecycle is not validated against the live remote before
   merge-gate resolution (F04–F05).

The candidates remain separate until their own probes show whether they share
either seam or have different causes.

## Next probe set

1. Run the full runner gap test with known-failure markers removed.
2. Trace one judge verdict from enqueue through drain to metrics storage.
3. Exercise a merge retry after remote base deletion and compare a fresh
   fetch with the freshness-skipped path.
4. Probe each documented candidate independently before changing code.
