---
name: principle-manage-idle-resumption
description: "Apply when a session may idle for a multi-hour or multi-day gap: polling loops, human-in-the-loop waits, overnight runs, babysit/watch/retry work. Compact or restart deliberately before resuming instead of letting the prompt cache lapse."
disable-model-invocation: true
---

# Manage Idle Resumption

A session that idles past its prompt-cache TTL (5 minutes by default, up to 1 hour with an explicit TTL) pays a full-price cache rebuild on the next turn instead of a cheap cache read — roughly 10x the per-token cost for however much context has accumulated.

**Why:** Long-running work — CI-repair loops, human-in-the-loop approval waits, overnight runs, polling for a merge or deploy to finish — naturally idles between turns. Each idle-then-resume silently re-bills the entire accumulated context at full price. Across a long session this recurs every time it idles, not once.

**Pattern:**
- Before letting a session sit idle for a multi-hour or multi-day gap, decide deliberately: compact now (summarize and trim), or accept the coming rebuild cost.
- For polling/watch loops specifically, batch checks rather than waiting synchronously turn-by-turn inside one growing thread — a detached poller that reports back once, instead of resuming the same context every N minutes, avoids paying the tax on every check.
- If a session naturally spans days (a long-running babysit task), schedule at least one compaction per idle gap, not one per context-window-full — the trigger is time, not size.
- Read the numbers, don't guess: `cache_read_input_tokens` near zero on a resumed turn, right after a gap, confirms the cache lapsed — that's the signal you should have compacted first.

**Battle-tested, across two different harnesses:** a corpus retrospective across this machine's worst-offender sessions found the same mechanism independently four times. A Claude Code CI-repair session paid three separate 200K–780K-token cache rebuilds, each immediately after a 2–4 hour idle gap. A second Claude Code session resumed after 6.5 hours and rebuilt 500K+ tokens of context across the next two turns. An OMP-harness session (a different tool entirely, same underlying mechanism) accumulated 29 cache-miss turns after idle gaps, costing $13.69 — 6.8% of that session's entire bill — versus neighboring turns with the same context size costing 10x less via cache hits. A fifth, 5-day-long session that never compacted paid the tax on every single resume; one instance alone cost 1.7M tokens to rebuild. In every case the trigger was elapsed wall-clock time since the last turn, not context size — a session well under its context-window limit can still be bleeding money on every idle-then-resume cycle.
