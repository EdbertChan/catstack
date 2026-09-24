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

## Bound shell transport (executable)

When a shell command may emit more than a small result, run it through the capture helper instead of letting stdout hit the parent:

```sh
python3 corpus/skills/principle-guard-the-context-window/scripts/capture_tool_result.py \
  --artifact-root "$TMPDIR/catstack-tool-captures" \
  -- \
  <command> <args...>
```

Hard parent body cap: **16384** UTF-8 bytes of combined stdout+stderr.

- Under the cap: the JSON stub includes `stdout` / `stderr` so small commands still work.
- Over the cap (or `gh run view --log` / `--log-failed`): the stub includes **no payload bytes**. It returns artifact paths, hashes, sizes, producer exit status, and an instruction to spawn a subagent.
- Full bytes stay on disk. The helper never chooses which lines are "relevant."

After an over-cap stub, spawn a **fresh read-only subagent** with:

1. The artifact `stdout_path` / `stderr_path` (or handle/root),
2. One specific question,
3. A bounded evidence budget (cite ranges; do not paste the whole file),
4. No writes.

The subagent inherits principle-subagent-inherits-scope: it answers only that question and does not widen it.

The parent receives only the answer plus cited ranges. **Count the subagent's tokens** toward total spend. A missing match or truncated subagent answer is not success. The parent must not `Read` the artifact unbounded.

When the companion native PreToolUse guard is installed (separate slice), recognized shell paths rewrite through this helper. That does not cover MCP results, file Read, screenshots, hosted tools, interactive stdin, or disabled/untrusted hooks — those remain named gaps.

## Concrete thresholds

**Shell / CLI body in the parent:** 16KiB combined stdout+stderr (enforced by the capture helper and, when installed, the bound-tool-result hook). The older "~200KB then subagent" line would have let a ~148KB CI job log through; that number was too high for shell dumps.

**Images / screenshots / full-file reads in the parent:** a single tool result over roughly 200KB (a screenshot, a video frame, a full-file read) should go to a subagent instead of staying inline. About to view or compare a 3rd image, or re-read the same file a 3rd time, in the main thread — delegate and bring back a short text verdict, not the payload.

**Battle-tested #2, cumulative drift without any single large payload:** a corpus retrospective found a session with zero tool errors and zero redundant reads — legitimate work throughout — that still burned 936K tokens of context before its first forced auto-compaction. Only 4 subagent/fork calls occurred across roughly 1700 turns, despite dozens of sequential grep/sed/cat dives into large source files spanning several unrelated worktrees. No single read crossed the image/file threshold above. The trigger isn't just "is this one payload big" — it's "is unresolved cross-file investigation piling up in this thread." Default to a fresh subagent with a written brief — the goal, the decisions already made, the files in scope, and what to return — before the 3rd or 4th exploratory dive into unfamiliar code, not only before the 3rd oversized read. A fork starts by copying the parent's entire context (median 562K tokens in a corpus retrospective, versus ~60K for a fresh subagent); reach for one only when the child genuinely needs that parent history to do the work, not by default.

**Battle-tested #3, a Skill invocation is a large payload too:** invoking a bundled reference skill for a single narrow fact — "pricing for two models" — loaded 922KB of unrelated per-language documentation into the main thread in one turn (verified against the bundled skill directory's own byte count), immediately followed by a cache-creation jump from ~3K to ~350K tokens. The skill wasn't misused — it just answers a broader class of question than the one actually asked, and there was no smaller reference to reach for instead. When a Skill call is likely to load far more than the question needs, consider whether a fork can answer the narrow question and report back a short verdict, the same way you'd delegate an oversized tool result — the mechanism (a large chunk of text entering the main thread's context) is identical either way. Related, not a rule change: fanning out many parallel `Agent` calls in one turn can independently blow the prompt-cache breakpoint (a ~590K-token context rewritten from scratch two seconds after ten agents launched, no idle gap or bug involved) — that's a real, uncounted cost of large fan-outs worth knowing about, not a reason to avoid them.
