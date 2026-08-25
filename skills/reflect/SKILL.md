---
name: reflect
description: Mine a conversation transcript — and the commit history of the files it touched — for durable learnings, then route the real ones into concrete skill edits through explicit user approval. Working-style preferences route to the sibling skill automate-me, not a task skill edit. User involvement, forced restatement, "you fucked up/messed up", or the same type of complaint twice is a FAILURE and must route to automate-me. Use when the user says reflect, after a complex multi-step task lands cleanly and the recipe is worth keeping, when the agent hit dead ends before finding a working path, or when the user corrected the agent's approach mid-task.
disable-model-invocation: true
---

# Reflect

Mine a transcript for durable learnings, then turn the real ones into skill edits — never silently.

Adapted from `pstack`'s `reflect` (cursor/plugins). Transcripts: Claude Code,
Cursor, Codex, and OMP — see [references/transcript-locations.md](references/transcript-locations.md).
Review fan-out uses the harness subagent tool (Claude Code: `Agent`; Cursor:
`Task`; `subagent_type: general-purpose` / `generalPurpose`). The parent
writes skill edits directly after approval.

Not every finding belongs in a skill edit here. A finding about the *user's working style or preferences* (not a code lesson) routes to the sibling skill `automate-me` instead — see step 4.

## Always run inside a subagent

Every invocation of this skill — single-transcript or multi-conversation mode — runs inside a subagent, no exceptions. The parent launches it with the harness subagent tool (`subagent_type: general-purpose` / `generalPurpose`: the process reads transcripts fresh from disk and doesn't need the parent's own conversation context) with the user's original reflect arguments/scope, then waits for it to report back. The subagent runs steps 1-4 (locate transcript(s), cost audit, lens fan-out, synthesis) — that's the large part. The parent runs steps 5 and 6 itself, in the main thread, never delegated: presenting the Accepted / Backlog / Route-to-automate-me / Rejected list and getting the user's approval, then applying the approved subset. This keeps the bulk of the investigation out of the parent's context window — the parent only needs the final synthesized findings list.

## When to invoke

- The `reflect-on-thrash` Stop/sessionEnd hook fired. Treat the named transcript as the scope; still wait for approval before any skill edit.
- The user said "reflect."
- A complex task (5+ tool calls) just landed cleanly and the recipe is worth keeping.
- The agent hit dead ends, found the working path, and the path generalizes.
- The user corrected the agent's approach mid-task.
- A non-trivial workflow emerged that isn't captured anywhere.
- A session, or a corpus-scan bucket, shows heavy user involvement — many corrections, clarifying answers typed out by hand, repeated manual confirmations — over a short span. That is a **FAILURE**, not a preference ping: the user had to stay in the loop because the agent missed a named constraint. Route to `automate-me` (step 4). Do not write a one-off task-skill edit and call it done.
- The user said "you fucked up", "you messed up", "I told you", "you're ignoring me", or equivalent agent-blame. Treat this reflect pass as FAIL. The class is *ignored named constraint*, not the swear word. Product-blame ("the UI is messed up") is not this class.
- The user had to keep iterating, restate requirements, or change product direction because the agent missed something already named. FAIL, then `automate-me`. A genuine mind-change (user learned new facts, then redirected) is not failure. A forced restatement of an already-named constraint is.
- The same *type* of complaint appears in 2+ turns or 2+ sessions (repro-then-fix, UI proof before done, e2e before claiming pass, obey the named verb). That class is a bug. **Must** invoke `automate-me` — not optional, do not wait for the user to say "automate me." `token_audit.py`'s `intervention-must-automate` flag is the mechanical catch; human-message only, never tool_result / skill-injection / `/loop` polls.
- It's been a while since the corpus-wide pass (`top_sessions.py` + this skill's lenses across the worst offenders) last ran. No fixed cadence and no cron — just periodically worth doing by hand.
- The user asks *why does X keep happening* across a span of time or across machines — that's **multi-conversation mode**; read [references/corpus-scan.md](references/corpus-scan.md).
- The invocation is itself an automated `reflect-ci-*` task with no human in the loop: run the step-3 sibling check unconditionally — concurrent automated dispatches produce exactly the duplicate-work burst a human would otherwise be there to notice.
- The **session-mine worker** marked a cluster `ready_for_headless` in `~/.cache/catstack-session-mine/queue.json` — see [references/session-mine.md](references/session-mine.md). That path uses **headless mode** (step 5b): GitHub PR review is the approval gate; never merge; never skip the repro fixture pair.

Skip when the conversation is trivial, off-topic, or already covered by a skill the parent followed correctly. One-offs are not learnings.

## Process

### 1. Locate the transcript(s)

**Single-transcript mode (default).** Read [references/transcript-locations.md](references/transcript-locations.md) for JSONL paths, message shape, and the Invoker tail caveat.

**Multi-conversation mode.** Read [references/corpus-scan.md](references/corpus-scan.md) for `corpus_scan.py` flags and remote SSH confirm-before-payload.

### 2. Run the cost audit, then spawn parallel reviewers

Token usage is exact data sitting in every transcript. Don't have an LLM reviewer eyeball the raw JSONL. Run the mechanical counter first, then hand its *output* (small, structured) to the Cost lens — never the raw file.

Read [references/cost-audit.md](references/cost-audit.md) for CLI (`token_audit.py`, including `--out`), thrash detectors, model-tier backtest, `top_sessions.py`, and tests.

### 3. Spawn parallel reviewers

Read [references/lenses.md](references/lenses.md) for the five lenses and the fix hierarchy. Prefer the cheapest check that still catches the mistake — do not write a skill line when a hook or test would do.

Before fanning out, check for sibling passes on the same incident: `git branch --all | grep -E "(reflect-ci|fix-ci)-<job-id>"` for concurrently dispatched fix/reflect branches, and `ls ~/.claude/projects/ | grep -F <incident-keyword>` for a sibling reflect's surviving transcript. A crashed sibling commits nothing — its synthesis lives only in its transcript tail; read that as prior art instead of re-deriving the same facts from zero. (Observed on an Invoker CI incident: one failing job accumulated three near-identical unmerged fixes and four full reflect fan-outs in a two-hour window, none aware of the others.)

### 4. Synthesize

One more `Agent` call, given all reviewers' output, merges overlapping findings and sorts into:

- **Accepted** — real, durable, worth acting on. Apply the elimination hierarchy from step 3 before slotting a finding here as a skill edit: if a reviewer proposed a skill/rule fix but a categorical or lint/test fix was actually available, bump it to Backlog with the stronger fix named instead, or split it.
- **Backlog** — real, but the right fix is higher up the hierarchy than a skill edit. Note which tier (1: categorical, 2: lint/test, 3: hook) each backlog item is.
- **Rejected** — one-offs, already covered, or too speculative.
- **Route to `automate-me`** — real, but it's about how *this user* likes to work rather than a lesson about the code or task. Don't inline these as edits to a task-specific skill; hand the finding to `automate-me`. Same-type complaints (2+ turns or 2+ sessions) and forced iteration / product-direction change after an agent miss are **mandatory** here, not optional. Invoke `automate-me` in the same turn if the user already asked to capture the preference, or name it as the first follow-up with evidence; do not wait for them to re-prompt.

### 5. Get approval — always (interactive)

Present the full Accepted / Backlog / Route-to-automate-me / Rejected list to the user and wait for explicit approval before touching any file. Skill edits affect every future session — never auto-apply. The user picks which subset to apply and may redirect routings.

If the session is an open product incident and synthesis already names a concrete product change, that change is the first offered action. Process hooks stay parallel backlog — do not offer only the hook or a proof plan when the named one-liner is what stops the live defect.

If `token_audit.py` flagged `intervention-must-automate: yes`, or synthesis found the same complaint type twice, the first offered action is invoking `automate-me` (alongside any product one-liner). That is not a style note.

### 5b. Headless / session-mine mode

When invoked by `session_mine.py` (or an agent following a `ready_for_headless` queue row), **do not** wait for chat approval. GitHub review is the gate:

1. Dedup: `git branch --all | grep reflect-` plus the cluster hash; skip if an open `[auto]` PR already names that hash.
2. Apply the fix hierarchy from [references/lenses.md](references/lenses.md) — hook/test before skill prose.
3. **Repro gate (hard):** every detector/skill/hook change in the PR MUST include a positive synthetic fixture (fires) and a negative fixture (stays silent), with tests. Run `python3 scripts/check_mine_repro_coverage.py` and `python3 scripts/check_hook_test_coverage.py` when hooks change. Refuse to open the PR if either fails.
4. Draft with `draft-pr` headless mode; title prefix `[auto]`; include cluster hash + bounded paraphrased quotes (no transcript paths, no secrets).
5. Push and `gh pr create`. **Never merge.** Then `session_mine.py mark-dispatched <hash>`.
6. Cap: at most one headless pass per cluster hash per week (enforced by the driver cooldown).

Interactive `/reflect` never uses 5b unless the user explicitly says the PR is pre-approved as the gate.

### 6. Apply the approved subset

- Before drafting, check whether an earlier reflect pass already drafted the same lesson but never landed it: `git log --all --grep=reflect -i -- <file>`, then `git merge-base --is-ancestor <candidate> HEAD`. A lesson that only exists on an unmerged branch is not in effect — adapt and land the prior draft, naming the duplicate branch in the summary, rather than writing a third divergent copy.
- Trivial edit (a corrected fact, a tightened sentence, a stale example): edit directly.
- Substantive edit (a new section, a new principle, more than ~10 lines): write it out in full, matching the target skill's existing structure and tone, and show the diff before it's considered done.
- Commit each applied edit immediately, not batched at the end of the step: a late crash or a blocked closing turn then loses nothing already applied. (Observed: a reflect pass drafted two skill edits, its closing summary was blocked by an unrelated hook with no further turn, and the edits survived only because the transcript did.)
- Backlog item: describe the concrete script/check/test to write, but don't write it as part of `reflect` itself — that's separate implementation work once the user confirms it's wanted.
- Route-to-`automate-me` item: don't draft it here. Either invoke `automate-me` directly if the user wants it done now, or leave it as a named follow-up in the summary below.

### 7. Summarize

Short list, no preamble:

- Edits applied: `<skill path>` — what changed, one line each.
- New skills created: `<skill path>` — one line each (rare).
- Backlogged: `<what to build>` — one line each, tagged with its tier and the evidence that motivated it.
- Routed to `automate-me`: one line each, with the evidence that motivated it.
- Dropped: one line per rejected finding + reason.
- Cost audit: total tokens, cache-read share, and the count of flagged thrash/model-tier items from `token_audit.py` — one line, with the real numbers.
- Feedback-loop check: recurring-failure-signature count and longest no-verify edit streak from `token_audit.py` — one line; call out explicitly if either was non-zero.
