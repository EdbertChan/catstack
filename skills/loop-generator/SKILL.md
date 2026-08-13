---
name: loop-generator
description: >
  Generate a reusable loop instruction doc and driver script for a recurring
  babysit/watch/retry task (e.g. "keep this PR merge-ready," "retry failed
  jobs until they pass," "watch this queue and fix what breaks"). Trigger:
  "loop generator", "generate a loop", or requests to build a reusable
  watch/retry loop.
---

# loop-generator

Generate two artifacts from a short interview: a loop instruction doc, and a loop driver shell script.

Generalized from a repo-specific skill that also generated a third artifact (a workflow-orchestrator YAML) — that part doesn't generalize since it assumed a specific internal workflow system. If your repo has an equivalent orchestrator, add that generation step back in; the interview and the two generic artifacts below don't depend on it.

## Conversational mode (default)

Treat this as a conversation before a draft.

- Talk through edge cases, corner cases, and ambiguity with the human before drafting.
- If anything important is unclear, ask concise questions instead of drafting.
- Draft only after the human asks you to draft/proceed, or the conversation has already resolved the important choices and the human gives explicit draft authorization.
- Ambiguity policy: explore first. If multiple real choices remain, ask. If only one boring default remains, continue and record it under an `Assumptions` note in the generated doc.

## Required interview schema

Collect and resolve every field below before drafting. Don't improvise a different schema.

1. `loop_name` — short human name.
2. `loop_slug` — kebab-case slug used in generated filenames.
3. `goal` — one-sentence end state.
4. `motivation` — why the loop exists.
5. `target_scope` — what entities the loop watches (PRs, jobs, queue items, etc.).
6. `target_discovery_command` — the exact command(s) or read-only query that define the live target set right now.
7. `target_identity_key` — the field used to dedupe targets across runs.
8. `success_criteria` — exact conditions that count as success.
9. `human_only_blockers` — conditions the loop should surface once and stop retrying, not loop on forever.
10. `evidence_sources` — ordered richest-to-cheapest sources the loop must consult before making a change.
11. `fail_condition_rule` — repeated-attempt threshold and grouping key (e.g. "3 failures on the same (target, symptom) pair → stop and report, don't keep retrying").
12. `local_proxy_command` — the safest repeatable local/proxy verification command, or `none`.
13. `write_mode` — one of `diagnostic_only` (never mutate, just report), `worker_owned_writes` (the loop itself makes changes), or `choose_each_run` (ask each time).

Interview rules:

- Ask for missing `success_criteria` before drafting — don't infer it from a vague goal.
- Ask for missing edge cases when `human_only_blockers`, `evidence_sources`, `fail_condition_rule`, or `write_mode` would materially change behavior.

Before drafting, post a short resolved summary: the filled fields, any defaults taken, open questions if any remain, and a direct check like "Ready to draft?"

## Loop instruction doc contract

Generate a doc with this exact section order:

1. `Goal`
2. `Real target` (what `target_discovery_command` actually returns, today)
3. `Success invariants`
4. `Fail condition`
5. `Evidence sources`
6. `Local proxy`
7. `Rebuild + rerun` (how the target set gets refreshed each round — never reuse a stale list)
8. `Loop` (the actual per-round procedure)
9. `Exit conditions`
10. `Constraints`

Rules:
- Make the real-world `write_mode` explicit in the doc — don't bury it.
- Keep `Goal`, `Motivation`, success rules, fail rules, and blockers concrete, not aspirational.
- Record assumptions explicitly instead of hiding them.
- Say what the live target is, how it's rebuilt each round, and how the loop dedupes it — don't hide mutable-state risk.

## Driver shell script contract

The generated driver must:

- parse `--target <id>` (repeatable), `--state-file <path>`, `--skip-local-check`, and `--help`;
- print loop context on start: cwd, branch (if applicable), and the state-file path;
- rebuild the live target set from `target_discovery_command` every run — never trust a cached list from a prior round;
- dedupe the target set by `target_identity_key`;
- print a repeated-failure summary keyed by `fail_condition_rule`, so a stuck target is visible instead of silently retried forever;
- when `--target` is passed for inspection, run any dry-run/probe command against a **copy** of mutable state, never the live state file;
- when `--skip-local-check` is not set and `local_proxy_command != none`, run it and exit non-zero on failure;
- print a final reminder that loop success is defined by `write_mode`, not by manual cleanup after the fact.

Safety rules:
- The inspection path must copy mutable state before any dry-run or probe command.
- Never let the driver silently widen from read-only inspection into live writes.
- If the target set comes from multiple commands, merge them, then dedupe by `target_identity_key`.

## Why the two-artifact split

The instruction doc is what a human (or an agent driving the loop) reads to understand intent, success/failure framing, and constraints. The driver script is what actually reruns deterministically. Keeping them separate means the doc stays reviewable prose while the script stays a real, rerunnable artifact — see `principle-build-the-lever`.
