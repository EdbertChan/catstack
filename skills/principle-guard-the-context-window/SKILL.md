---
name: principle-guard-the-context-window
description: "Apply when context is filling up: large outputs, long files, repeated reads, fan-out planning. Route bulk to subagents; keep summaries in the main thread, not raw payloads."
disable-model-invocation: true
---

# Guard the Context Window

The context window is finite and non-renewable within a session. Every token that enters should earn its place.

**Why:** Context overflow degrades reasoning quality, creates compression artifacts, and halts progress. Unlike compute or time, context spent inside a session cannot be reclaimed.

**Pattern:**
- **Isolate large payloads.** Route verbose outputs, screenshots, and large documents to subagents. The main context gets summaries, not raw data.
- **Don't read what you won't use.** Read selectively based on relevance. If a file isn't needed for the current task, skip it.
- **Keep frequently used content inline.** Templates and references used on every invocation belong in the skill file, not in separate files that cost a read each time.
- **Size phases and cap scope.** Limit files per phase, set turn budgets, account for mechanism costs.

**Battle-tested, with a concrete threshold:** a 13MB session hit forced compaction after accumulating multiple 250–330KB inline image results in the main thread, with almost no subagent delegation the whole session. The rule as written ("route verbose outputs to subagents") is correct but has no number attached, so it's easy to keep telling yourself "just one more" until compaction forces the issue. Two concrete triggers: a single tool result over roughly 200KB (a screenshot, a video frame, a full-file read) should go to a subagent instead of staying inline; about to view or compare a 3rd image, or re-read the same file a 3rd time, in the main thread — delegate that work and bring back a short text verdict, not the payload.

**Battle-tested #2, cumulative drift without any single large payload:** a corpus retrospective found a session with zero tool errors and zero redundant reads — legitimate work throughout — that still burned 936K tokens of context before its first forced auto-compaction. Only 4 subagent/fork calls occurred across roughly 1700 turns, despite dozens of sequential grep/sed/cat dives into large source files spanning several unrelated worktrees. No single read crossed the 200KB threshold above. The trigger isn't just "is this one payload big" — it's "is unresolved cross-file investigation piling up in this thread." Fork a research subagent before the 3rd or 4th exploratory dive into unfamiliar code, not only before the 3rd oversized read.
