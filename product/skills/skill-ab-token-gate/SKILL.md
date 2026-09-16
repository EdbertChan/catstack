---
name: skill-ab-token-gate
description: >-
  After changing a skill or hook meant to cut context/token cost, run a paired
  A/B workload N times (default 5), aggregate native parent+subagent tokens,
  publish a GitHub gist with the report and raw session JSONL, and only treat
  the change as validated when treatment median inclusive tokens beat control.
  Expand later to other models; default harness is Codex rollout usage.
---

# Skill A/B token gate

A skill or hook change that claims to save tokens is unverified until a
paired A/B run shows it under the same workload.

**Why:** One lucky run is noise. Inline "it felt cheaper" is not evidence.
Native session totals (parent + collaboration subagents) plus a rerunnable
gist are the checkable artifact.

**When:** After editing a skill/hook whose purpose is smaller context or
fewer tokens (capture wrappers, PreToolUse rewrites, guard-the-context
recipes). Not for unrelated skill edits.

## Invariants (assert)

1. **Paired arms.** Control (A) = without the change (or without the treatment
   prompt/profile). Treatment (B) = with the change. Same workload YAML/prompt
   family otherwise.
2. **N >= 5 by default.** Fewer only when the user names a smaller N. Include
   every finished rep in the aggregate; do not drop outliers by hand.
3. **Inclusive tokens.** For each run: last `total_token_usage` on the parent
   Codex rollout **plus** every collaboration child discovered via
   `agent_thread_id` / `spawn_agent`. Report both `total_tokens` and
   uncached+output.
4. **Same model pin across arms** for a given batch. Multi-model expansion is
   a later axis (one model per batch; do not mix models inside one aggregate).
5. **Gist is the record.** Publish `REPORT.md`, `aggregate.json`, `registry.json`,
   and raw `session-*.jsonl` files. Link any GitHub PRs the arms opened.
6. **Pass gate.** Treatment wins only when median inclusive `total_tokens` for
   B is **strictly less than** A (or the user named a different threshold).
   Record mean and stdev too; do not pass on mean alone when medians disagree.

## Recipe

1. Write or reuse a fixed workload (same goal, same large-payload trigger).
2. Tag each plan with a unique arm+rep id (`…-A-r1` … `…-B-r5`).
3. Pilot one head until its implement task is running, then submit the remaining paired plans.
4. On settle, run:

```sh
python3 product/skills/skill-ab-token-gate/scripts/aggregate_ab_runs.py \
  --registry /path/to/registry.json --out /path/to/out
python3 product/skills/skill-ab-token-gate/scripts/publish_ab_gist.py \
  --out /path/to/out [--gist-id <id>]
```

5. Paste the gist URL and the pass/fail line into the skill-change PR or chat.

## Domain selector

After reading this file, read **at most one** sibling `domains/<type>.md`:

1. User named the type (`coding`, `equities`).
2. Else cwd has `.cursor/judge-swarm-bindings.json`, or equities trigger words
   → `equities`; Invoker / catstack / `package.json` without those → `coding`.
3. Else none.

## Do not

- Declare a token win from a single run.
- Compare arms that used different models in one batch.
- Count Invoker verify/merge-gate sessions as collaboration subagents.
- Skip the gist when sessions exist on disk.
