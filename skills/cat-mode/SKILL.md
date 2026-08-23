---
name: cat-mode
description: >
  Edbert's personal working conventions, mined from real session history
  across his projects. Use when Edbert asks to "work in my style," invokes
  this by name, or asks how he generally likes things done. Covers
  autonomy/delegation defaults, the "fix the tool, not just the instance"
  habit, subagent usage, and verification posture beyond what CLAUDE.md's
  evidence rules already cover.
disable-model-invocation: true
---

# cat-mode

Personal conventions, not a task-specific skill. For response shape and
brevity, use `diu` — it's the always-on default and already covers this;
nothing here duplicates it.

## Autonomy

Once direction is set, act — don't ask permission for each sub-step. The
user hands off multi-step work with one fully-specified directive ("babysit
these PRs, land bottom to top, repair as needed, don't stop until they all
land") and expects the agent to self-manage parallelism and only check back
when something structurally changes, not to narrate progress.

- **Commit and push automatically, right after a change is verified —
  don't wait to be asked.** The user says "commit and push" as a trailing
  command dozens of times across sessions; treat that as the standing
  default rather than something to request each time. This does NOT extend
  to deploys or other production-visible actions — those still get asked
  first, same as CLAUDE.md's general risk guidance.
- Prefer doing the thing over handing back instructions to run manually
  ("can you start it for me," "why don't you just do it for me"). Reserve
  manual steps for things the agent genuinely cannot do (interactive OAuth
  consent, a store dashboard upload).
- Destructive or hard-to-reverse actions (force-push, bypassing a merge
  queue guard, schema changes) still get a stop-and-ask — and hold the line
  even when asked directly to bypass a safety rule. The user has tested this
  more than once and treats the agent holding firm as correct, not
  obstructive.
- For a genuinely ambiguous or large ask, ask clarifying questions up front
  rather than guessing and redoing — the user has said this explicitly, in
  close to these words, more than once: "ask me questions about ambiguity
  and edge cases" before building.
- When offering `AskUserQuestion` choices, don't assume "(Recommended)" is
  always the safe bet to lean on — the user picks it when it's working and
  switches to a more active option once evidence shows the passive path
  isn't (e.g. escalating from "keep waiting" to "give me direct access"
  once a queue kept growing for hours). Recommend based on what's actually
  happening, not a reflexive default.

## Fix the tool, not just the instance

The single most repeated pattern across this user's history: when a bug,
gap, or one-off request reveals a structural problem, extend the underlying
skill/script/process so the same gap can't recur — don't just patch the
symptom in front of you. Seen as: "can we update the pr skill or something
so this doesn't happen again," rewriting a skill's step ordering after it
let a real mistake through, building `diu` itself out of a mined pattern
rather than fixing one bad response.

- Propose the structural fix and get sign-off before executing it — this
  is exactly what `reflect`'s Accepted/Backlog/Rejected approval gate is
  for. Don't silently go rewrite a skill because it seems like the right
  move; show the diff and let the user decide. Once a findings list is
  backed by real evidence (incidents, commit hashes, direct quotes), the
  user tends to bulk-approve it whole ("apply all of them") rather than
  negotiate item by item — a well-evidenced synthesis earns that trust;
  don't hold back on presenting the full list because some items seem
  minor.
- Before trusting a new rule, skill, or number, backtest it against real
  past conversations — "battle test this on our past conversations," "back
  test it against my conversations, which one works, which one doesn't"
  comes up repeatedly. A rule that sounds right but hasn't been checked
  against real transcripts is a draft, not a rule.
- Before adding a new skill, check whether an existing one already covers
  it and consolidate instead of layering a near-duplicate on top (this is
  exactly why `i-have-adhd`'s rules now live inside `diu` instead of as a
  second, overlapping skill).
- Skills and hooks are expected to work the same way across every harness
  the user runs (Claude Code, Codex, Cursor) and every machine — a skill
  that only works in one place is unfinished, not a first draft to ship.
- When a repeated task settles into "check status, wait, repeat" for 3+
  cycles, flag it as an automation candidate before being asked — the user
  wants both the task automated and the habit of noticing that automation
  opportunity to become the default, not just the one instance fixed
  ("how can we automate this? and automate the automation?").
- Prefer extending an existing durable mechanism over adding a new one-off
  script or cron for the same class of problem — grow an existing skill/loop,
  or an Invoker worker when that runtime is available, instead of a sibling
  mechanism next to it.
- When a shared instruction file (CLAUDE.md, a skill) is getting bloated —
  one bullet ballooning into a wall of text from repeated appends — point
  it out and default to restructuring it properly (split rule from
  precedent/examples) rather than appending one more line to the mess or
  leaving it alone because the immediate task didn't ask for it.

## Execution routing

Read [references/execution-routing.md](references/execution-routing.md).
Executable decision table: `scripts/route_execution.py` (used by tests).
Default local. Delegate to Invoker only when its MCP tools are available and
the work is an approved plan or durable/parallel execution; then prepare
review → one approval → submit → bounded status/wait → report.

## Subagents

Default to delegating, not doing it all inline — reach for a subagent
whenever a piece of work is separable, not only for bulk/investigation
tasks. Research, verification, independent file-scoped work, anything
whose output doesn't need to stay in the main thread's context: fork or
spawn it rather than burning the main conversation's context on it. The
user delegates in bulk, not one task at a time — "land all the
admin-bypass PRs and babysit them through to master, fixing conflicts as
needed," not a single PR — so default to parallel background/worktree-
isolated subagents and report back async rather than blocking on each one.

## Verify

CLAUDE.md's evidence rules (real command output, repro-before-and-after,
no unverified "fixed"/"works" claims) are already the default and this
user's own session behavior matches them closely — don't duplicate that
here. One addition specific to this user: don't declare something fixed
after a single attempt if the fix can be re-checked cheaply — loop until a
fix is actually confirmed working, not just applied once ("keep looping
and fixing and proving repro cases... until we're able to queue up
cleanly"). Unattended, babysit, overnight, or multi-phase local runs also
keep a `show-me-your-work` decision log so the user can review without
replaying the transcript — that diary is not a substitute for the
same-turn evidence gate.

For a waste/cost/audit-style report specifically, build the full-scope,
real-data version on the first pass, not a narrow or illustrative one —
the user escalated the same request three separate times in one session
(a narrative estimate → real numbers → all sessions → all machines)
before getting the version actually wanted, matching an identical
escalation shape from a prior session ("is this across all DO
machines"). Skip the illustrative middle step for this request type.

When a report and a repo/tool are requested together, the repo (or its
README) is the one artifact-of-record — don't also publish a disconnected
one-off write-up alongside it. A real number produced mid-session gets
written back into that one place in the same turn, not left sitting only
in chat until the user has to ask for it again.

## Prose & scope discipline

- Answer the literal question asked before adding related context. Burying
  a direct answer under adjacent material draws sharp, immediate pushback
  ("You are ignoring my instructions and words! I am asking you literally
  why X is failing and you are talking about Y???"), especially the second
  time the same question has to be re-asked.
- When the user finds a bug themselves, they expect a regression test as
  part of the fix as a matter of course, not something to ask about.
- Architecture and design choices get questioned, not accepted at face
  value — "why aren't they sharing the same logic," "I'm not convinced X is
  right, why not Y" — have the rationale ready, or admit there isn't one
  and reconsider.
