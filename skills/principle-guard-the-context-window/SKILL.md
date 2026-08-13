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
