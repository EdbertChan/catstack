---
name: reflect
description: Mine a conversation transcript for durable learnings, then route the real ones into concrete skill edits through explicit user approval. Use when the user says reflect, after a complex multi-step task lands cleanly and the recipe is worth keeping, when the agent hit dead ends before finding a working path, or when the user corrected the agent's approach mid-task.
disable-model-invocation: true
---

# Reflect

Mine a transcript for durable learnings, then turn the real ones into skill edits — never silently.

Adapted from `pstack`'s `reflect` (cursor/plugins), rewritten for Claude Code: transcripts live under `~/.claude/projects/`, review fan-out uses the `Agent` tool, and there's no `create-skill` built-in to hand substantive edits to — the parent writes them directly.

## When to invoke

- The user said "reflect."
- A complex task (5+ tool calls) just landed cleanly and the recipe is worth keeping.
- The agent hit dead ends, found the working path, and the path generalizes.
- The user corrected the agent's approach mid-task.
- A non-trivial workflow emerged that isn't captured anywhere.

Skip when the conversation is trivial, off-topic, or already covered by a skill the parent followed correctly. One-offs are not learnings.

## Process

### 1. Locate the transcript

Claude Code stores session transcripts as JSONL under `~/.claude/projects/<encoded-cwd>/*.jsonl`, where `<encoded-cwd>` is the absolute working directory with every `/` replaced by `-` (e.g. `/Users/x/repo` → `-Users-x-repo`). Take the most recently modified file in that directory unless the user names a different project or session. Each line is JSON with a `type` field (`"user"` / `"assistant"` carry the conversation; skip other types like `mode` or `file-history-snapshot`); message text is at `.message.content`, either a plain string or a list of blocks (`text`, `thinking`, `tool_use`, `tool_result`).

### 2. Spawn parallel reviewers

One message, parallel `Agent` calls (`subagent_type: general-purpose`), each given the transcript path and a distinct lens:

| Lens | Looks for |
|---|---|
| Judgment | Where the reasoning or approach wobbled — a wrong assumption, a fix that didn't address the real cause, scope that crept. |
| Tooling | Anything that should have been a script, lint, or runtime check instead of an instruction a human has to remember and re-follow. This is `principle-encode-lessons-in-structure` and `principle-build-the-lever` applied to the session itself. |
| Divergent | Whatever the other two lenses would miss — an unconventional angle, a blind spot, a pattern that only shows up zoomed out. |

Each reviewer returns candidate learnings as: what happened (with a quote/reference), why it matters, and a suggested routing (edit an existing skill / draft a new skill / add an enforcement script / drop).

### 3. Synthesize

One more `Agent` call, given all three reviewers' output, merges overlapping findings and sorts into:

- **Accepted** — real, durable, worth acting on.
- **Backlog** — real, but the right fix is a script/lint/check, not more skill prose. Anything mechanically enforceable belongs here, not in Accepted.
- **Rejected** — one-offs, already covered, or too speculative.

### 4. Get approval — always

Present the full Accepted / Backlog / Rejected list to the user and wait for explicit approval before touching any file. Skill edits affect every future session — never auto-apply. The user picks which subset to apply and may redirect routings.

### 5. Apply the approved subset

- Trivial edit (a corrected fact, a tightened sentence, a stale example): edit directly.
- Substantive edit (a new section, a new principle, more than ~10 lines): write it out in full, matching the target skill's existing structure and tone, and show the diff before it's considered done.
- Backlog item: describe the concrete script/check/test to write, but don't write it as part of `reflect` itself — that's separate implementation work once the user confirms it's wanted.

### 6. Summarize

Short list, no preamble:

- Edits applied: `<skill path>` — what changed, one line each.
- New skills created: `<skill path>` — one line each (rare).
- Backlogged: `<what to build>` — one line each, with the evidence that motivated it.
- Dropped: one line per rejected finding + reason.
