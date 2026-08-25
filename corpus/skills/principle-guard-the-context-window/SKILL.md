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
- **File-then-parse.** Never pipe a large CLI dump (trace JSON, multi-MB transcript, long log) straight into the main thread or through a pipe that the harness truncates (~30KB on Claude Code Bash). Redirect to a file first, then `jq` / read only the fields you need. Prefer extract-fields or a small structured report over fetching the full payload when the tool supports it.
- **Don't read what you won't use.** Read selectively based on relevance. If a file isn't needed for the current task, skip it.
- **Keep frequently used content inline.** Templates and references used on every invocation belong in the skill file, not in separate files that cost a read each time. Progressive disclosure is the inverse: put rarely-needed bulk in `references/` and load it only when that step runs.
- **Size phases and cap scope.** Limit files per phase, set turn budgets, account for mechanism costs.

**Battle-tested, with a concrete threshold:** a 13MB session hit forced compaction after accumulating multiple 250–330KB inline image results in the main thread, with almost no subagent delegation the whole session. The rule as written ("route verbose outputs to subagents") is correct but has no number attached, so it's easy to keep telling yourself "just one more" until compaction forces the issue. Two concrete triggers: a single tool result over roughly 200KB (a screenshot, a video frame, a full-file read) should go to a subagent instead of staying inline; about to view or compare a 3rd image, or re-read the same file a 3rd time, in the main thread — delegate that work and bring back a short text verdict, not the payload.

**Battle-tested #2, cumulative drift without any single large payload:** a corpus retrospective found a session with zero tool errors and zero redundant reads — legitimate work throughout — that still burned 936K tokens of context before its first forced auto-compaction. Only 4 subagent/fork calls occurred across roughly 1700 turns, despite dozens of sequential grep/sed/cat dives into large source files spanning several unrelated worktrees. No single read crossed the 200KB threshold above. The trigger isn't just "is this one payload big" — it's "is unresolved cross-file investigation piling up in this thread." Fork a research subagent before the 3rd or 4th exploratory dive into unfamiliar code, not only before the 3rd oversized read.

**Battle-tested #3, a Skill invocation is a large payload too:** invoking a bundled reference skill for a single narrow fact — "pricing for two models" — loaded 922KB of unrelated per-language documentation into the main thread in one turn (verified against the bundled skill directory's own byte count), immediately followed by a cache-creation jump from ~3K to ~350K tokens. The skill wasn't misused — it just answers a broader class of question than the one actually asked, and there was no smaller reference to reach for instead. When a Skill call is likely to load far more than the question needs, consider whether a fork can answer the narrow question and report back a short verdict, the same way you'd delegate an oversized tool result — the mechanism (a large chunk of text entering the main thread's context) is identical either way. Related, not a rule change: fanning out many parallel `Agent` calls in one turn can independently blow the prompt-cache breakpoint (a ~590K-token context rewritten from scratch two seconds after ten agents launched, no idle gap or bug involved) — that's a real, uncounted cost of large fan-outs worth knowing about, not a reason to avoid them.
