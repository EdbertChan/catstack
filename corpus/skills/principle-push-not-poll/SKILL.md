---
name: principle-push-not-poll
description: "Apply when designing, reviewing, or authoring any mechanism that waits on a long-running background action: a CI/build watcher, a deploy or merge poller, a status-check loop, an agent babysitting a backgrounded command. Prefer a push/wakeup signal over a tight poll loop."
disable-model-invocation: true
---

# Push, Not Poll

A poll loop that re-sends or re-evaluates growing state on every check compounds cost near-quadratically in check count, not linearly in wall-clock time. Waiting longer isn't the expensive part — checking often is.

**Why:** When a system waits on a long-running background action inside a growing conversation or log, each poll re-transmits (and often re-bills, via cached-input pricing) the entire accumulated state so far, not just the delta since the last check. Tightening the poll interval doesn't just add checks linearly — it multiplies the resend cost by a state size that is itself growing with every check. The fix isn't "poll less" as a vague instinct; it's recognizing that a push/wakeup notification (the background action tells the watcher when it's done) pays for the wait once, while a poll loop pays for it once per check.

**Pattern:**
- Prefer a callback, webhook, event, or completion signal from the long-running action itself over a caller that repeatedly asks "are you done yet?"
- If no push mechanism exists and polling is unavoidable, widen the interval and cap the check count — don't poll on a fixed short cadence for an unbounded or long wait.
- Treat "we polled every N seconds for M minutes" as a red flag in review, not a neutral implementation detail — ask whether N was chosen for responsiveness or just left at a default.
- When a poll loop resends conversation/log history on each check, the cost driver is check count × accumulated state, not check count alone — cheaper to grow the interval than to trim the state per check.
- If you control both sides (the waiter and the thing being waited on), add the push path rather than tuning the poll harder.

**Battle-tested:** Invoker's fix-ci auto-repair sessions backgrounded a 15–45 minute verify command and polled it every 10–30 seconds, each poll re-sending the whole growing conversation as cached input — 50–125M tokens burned per session. Measured against Invoker's fix-ci-token-bench simulator: a 10s-cadence, no-cap polling policy cost 74,147,000 tokens for a 45-minute wait; a 180s-cadence, 15-check-cap policy cost 966,000 tokens for the same wait — a 98.7% reduction, now gated permanently into Invoker's pnpm test. The mechanical, Invoker-specific implementation of this principle for workflow/worker authors lives outside this repo as the Invoker skill named push-not-poll (Invoker PRs #11887–#11891) — this skill is the general, harness-agnostic version of the same lesson.
