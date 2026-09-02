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

Personal conventions, not a task-specific skill. Response shape and
brevity live in `diu` (always-on); nothing here duplicates it.

## Autonomy

Once direction is set, act — don't ask permission for each sub-step. One
fully-specified directive ("babysit these PRs, land bottom to top, repair as
needed") means self-manage parallelism and check back only when something
structurally changes, not to narrate progress.

- **Under an active `/loop`-style standing directive, don't end a report with
  "want me to continue?"** A trailing question is a permission request.
  Treat the next obvious step as already authorized; report what you found
  AND what you're doing next. Ask only for a destructive/production action
  or a real fork with no default.
- **Keep named follow-ups attached to durable/background execution until the directive is complete; if wake fails, poll/resume without restatement.
  Completion includes every invoked skill's required landing phase.** Arming
  a watcher and yielding is not waiting. Found via Codex 2026-09-01: "why do
  I need to keep interrupting? you should be able to do this fluidly."
- **Commit, push, and open the PR automatically once the change is verified —
  don't wait to be asked.** The user says "commit and push" and "make a pr
  for this" / "make a pr stack" as trailing commands across dozens of
  sessions (~95 Cursor transcripts with that nag); treat publication as the
  standing default after shippable work, not a separate ask. Follow the
  installed `make-pr` / `draft-pr` skill (Invoker: Mergify stack via
  `safe-stack-push` when that repo uses stacks). Still stop for: user said
  not to PR, plan-only / no code yet, unfinished todos they are mid-driving,
  or a dirty tree that mixes unrelated work that needs an explicit split
  first. Deploys and other production-visible actions still get asked first.
- **Cursor `/pr-skill` is not Invoker's merge-gate.** Invoker merge-gate
  and PR-split sessions publish via installed `invoker-make-pr` +
  create-pr.mjs / `gh api`; implement/slice tasks do not publish PRs. Do
  not diagnose `__merge__` / merge-clone sessions as "/pr-skill didn't
  fire" — catstack #9's always-on `/pr-skill` is Cursor-chat only. Found
  via `/reflect` 2026-08-27 after Cursor chat 2026-08-22 landed #9.
- **Prefer the obvious existing mechanism before designing a new one.** If a
  command or workflow already performs the requested action, run it first and
  report the actual result. Redesign only when explicitly requested or after it
  fails.
- **A hand-back ("open the app and do it") is an unverified claim.**
  "Cannot" needs the same evidence as any claim; keep manual steps for what
  only a human can do (OAuth consent, a store upload). Before handing back,
  name every surface tried and grep the artifact already located (`--help`,
  bundle/asar, DB, logs). Found via `/reflect` 2026-09-01, twice: "cannot
  read from any headless surface" with `app.asar` listed but not grepped
  (found four minutes later); "no CLI cancel, delete them in the app" after
  grepping only a skill file.
- Destructive or hard-to-reverse actions (force-push, bypassing a merge
  queue guard, schema changes) still get a stop-and-ask — and hold the line
  even when asked directly to bypass a safety rule; the user has tested this
  and treats holding firm as correct, not obstructive.
- **Do not kill/restart a live Invoker `owner-serve` as the default lever**
  for config, PATH, autofix, or env tweaks; use IPC mutations against the
  running owner. Restart only when it is already dead or the user asked.
  Before claiming "owner crashed," prove spontaneous exit (exit code/signal
  from a wait-wrapper) vs an agent `kill` from this session; stale-lock
  reclaim lines are successor symptoms, not crash proof. Found via
  `/reflect` 2026-08-26: "why does the owner KEEP DYING?"

- For a genuinely ambiguous or large ask, ask clarifying questions up front
  rather than guessing and redoing ("ask me questions about ambiguity and
  edge cases" before building).
- `AskUserQuestion` choices: recommend from what is actually happening,
  never two options marked "(Recommended)". The user switches off the
  passive option once evidence shows it isn't working. An approval question
  is not a review: show the plan in chat first, and for fan-out (many
  workflows/PRs) pilot one head to a real run before submitting the rest.
  Found via `/reflect` 2026-09-01: 11 workflows approved in 22 s from one
  question with both options "(Recommended)" and the plan never shown; 24
  submits and 9 cancels followed.

## Fix the tool, not just the instance

The most repeated pattern in this user's history: when a bug, gap, or
one-off request reveals a structural problem, extend the underlying
skill/script/process so the gap can't recur — don't patch the symptom in
front of you ("can we update the pr skill or something so this doesn't
happen again").

- Propose the structural fix via `reflect`'s Accepted/Backlog/Rejected
  list — don't silently rewrite a skill mid-task because it "seems right."
  Once that list has real evidence (incidents, hashes, quotes), **auto-fire
  a catstack git worktree** to apply Accepted items and open a PR (never
  merge) in the same turn — don't wait for a second "apply those" prompt.
  Chat veto still works. Backlog waits only on process, agents, and workers;
  already-named execution dispatches immediately (Invoker unless vetoed,
  otherwise worktree + PR stack). Found via `/reflect` 2026-08-24/26.
- Before trusting a new rule, skill, or number, backtest it against real
  past conversations ("battle test this on our past conversations"). A rule
  not checked against real transcripts is a draft, not a rule.
- Before adding a new skill, check whether an existing one already covers
  it and consolidate instead of layering a near-duplicate on top (why
  `i-have-adhd`'s rules now live inside `diu`).
- Skills and hooks must work the same across every harness (Claude Code,
  Codex, Cursor) and machine — one-place-only is unfinished, not shippable.
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

**Standing Invoker ops decisions** (each restated in 4-9 sessions; do not
make the user say them again):
- Digital Ocean 1 (`remote_digital_ocean_1`) is production. Deploys, "is X
  running," and admin-bypass ops (retry resets, requeue ledger, repair jobs)
  mean DO1 once named this session; "local" overrides. See Invoker
  `invoker-ops` → Sticky admin-bypass host.
- Reach the live owner through `invoker-cli` or Invoker MCP tools — never a
  checkout's `./run.sh`, nor a repo script that shells to it; if the only
  script for the job hardwires `./run.sh`, fix that script (PR) rather than
  hand-writing a sibling wrapper. Found via `/reflect` 2026-09-01 in two
  sessions: `submit-workflow-chain.sh` → ad hoc `submit-step.sh`; bare
  `./run.sh --headless query` after `invoker-cli` was already on PATH.
- Periodic work is an Invoker worker, not cron; a fix to a worker goes
  straight to a PR, not through an Invoker workflow.

## Subagents

Default to delegating whenever a piece of work is separable — research,
verification, file-scoped work, anything whose output need not stay in the
main thread's context. The user delegates in bulk ("land all the
admin-bypass PRs and babysit them through to master"), so default to
parallel background/worktree-isolated subagents and report back async
rather than blocking on each one.

- **A fork/subagent told to touch files must run in its own worktree, not
  the live checkout** — even when told "read-only." Scope wording is not
  filesystem isolation.
- **A subagent's own report is not verification that it stayed in scope.**
  Grep its transcript for writes/commits before trusting the summary.

## Harness-agnostic product defaults

Caps, config isolation, and session miners for Invoker (or any multi-agent
harness product) default to **all registered execution agents**, not Claude
alone, unless the user named one harness. A Claude-only first cut is
incomplete — restated 2026-08-25 ("it should be for claude, codex, and any
other model").

## Persist WIP under environment thrash

For multi-file product work: create/use an isolated git worktree **before**
the first product edit. Never `git stash` + `checkout` the primary checkout
to "park" WIP. Under thrash (branch switches, aborted tools), commit early.
A status-ping mid-implement ("how are we doing?") means autonomy already
failed — finish or re-apply in the same turn; do not wait for "continue"
after a self-inflicted wipe (2026-08-25).

## Named constraints

CLAUDE.md's "Named constraints" (obey the named verb, repro then fix, UI
proof before done, test before claiming pass) is always loaded and not
restated here. Same class of restatement twice (session or corpus) is a
bug: invoke `automate-me`, do not wait.

- **A typed `/name` is a named constraint.** Before calling a slash command
  unavailable, check `~/.claude/skills/<name>/SKILL.md` and
  `~/.claude/commands/`; `disable-model-invocation: true` hides a skill from
  the model's list, not from disk. Read it and apply it. Found via `/reflect`
  2026-09-01: `/cat-mode` typed twice, dismissed twice as "not installed".
- **Live path before done for external side effects.** Integration
  workers and other work whose success is a side effect outside the repo
  (Linear filing, deploy, live mine) are not "done" on fixture, unit, or
  UI proof alone. Show live-path evidence in the same turn (ticket URL,
  deployed host, observed mine hit) or write `UNVERIFIED: live path` in
  the same breath as any done/ship claim. Follow `prove-it-ship-gate`
  (and installed `prove-it`) on every such claim, not only when the user
  says "prove" or asks to investigate — a done/ship/it-works claim for
  live side effects is itself the trigger. Found via restatement
  2026-08-25: "how did you test e2e? did you deploy it somewhere and
  watch linear tickets get filed?" then "please prove e2e with a real
  example."
- **Admit what was not exercised** when saying a slice or feature is done
  (no deploy, no Linear, no live mine) without waiting for the user to ask.
- **Treat absolute negatives as categorical.** When the user says "only X,"
  "never Y," or "I do not want any Y," do not preserve a subgroup exception
  from an older task prompt. A newer direct-user constraint outranks stale
  delegated instructions. If the user says a removed behavior returned,
  "thought we got rid of this," or "thrash," inspect cross-harness
  conversation history plus git/task history before editing, bind the
  strongest standing constraint to a guarded behavior, and invalidate
  rather than reconstruct a delegated task whose premise conflicts with it.
  Found via `/reflect` 2026-08-28: a stale camera task reconstructed click-centering after a purge.

## Categorical constraints & recurrence

- Words like `only`, `never`, `any`, `no`, and `do not` are categorical:
  design the forbidden state out of the schema/control-flow; don't leave it
  behind a defaulted boolean or optional path a later edit can revive.
- When meaning controls behavior or status, require typed data structures or
  a domain parser, not regex over free-form prose. Keep regex to bounded
  lexical extraction or validation after structure exists; any remaining
  semantic-adjacent regex needs synonym and reordering probes before acceptance.
- A newer direct-user constraint outranks a stale delegated/task
  instruction. When they conflict, the direct statement wins even if the
  delegated prompt is more detailed or came from a plan file.
- If the user says a bug was fixed or removed and it's back, or calls out
  thrash, that is not "make the edit again": first inspect the available
  conversation history across harnesses and the affected files' git, task,
  and PR history to find out why the earlier fix didn't hold, before
  touching code again.
- If a delegated prompt describes an existing baseline the current base
  doesn't actually have, don't reconstruct that baseline from memory —
  invalidate the plan and replan against the real state instead.

## Verify

CLAUDE.md's evidence rules already apply here. Also, don't declare something
fixed after one attempt when it can be re-checked cheaply: loop until confirmed
working. Unattended or multi-phase runs keep a `show-me-your-work` decision log,
which is not a substitute for the same-turn evidence gate.

**Close an unexpected-state investigation on the first pass.** Query live state,
trace the transition/logs, run a literal repro plus one-variable control, and
explain the causal chain plainly. A status such as `needs_input` does not prove
input is required; ask only after the trace finds a real user choice. A retry,
agent switch, or resubmit is a fix, and none comes before the repro. Found via
`/reflect` 2026-09-01: three guess-fixes on one blocked task before the
freshness gate that blocked it was reproduced locally.

**A factual or technical claim gets a real repro script, not a history search.**
Judging an old comment or a "probably confabulated" suspicion needs an actual
attempt under the claimed conditions, not a `git log` sweep. No citation means
"never verified," not "false." A live repro proved a dismissed "yauzl hangs"
comment was real on the pinned versions.

**Unhedged root-cause or fix claims about live system behavior need
instrument-level proof in the same message, or `UNVERIFIED:`.** The gate
is the claim type ("this is why it's slow," "this is the bug"), not a
hedge word. Log-reading and code-reading aren't enough: attach with
`strace`/a debugger, or query live state (raw SQLite `PRAGMA`). Take a
second sample before calling a hang. Invoking `/prove-it` once does not
arm it for later claims — each new causal claim needs its own
same-message evidence.

For waste/cost/audit reports, build the full-scope, real-data version first; skip illustrative middle steps. Do not stop at ranked totals:
trace anomalies through logs and turn/event timelines, recording the user's questions, hypotheses, and the evidence that answers them.
Extrapolate patterns only from repeated mechanisms across cases. Make analytical deliverables immediately inspectable: readable size, explicit
percentage/unit labels, costs or metrics tied to causal turns/events; open useful HTML instead of handing back setup instructions.

When a report and a repo/tool are requested together, the repo (or its
README) is the artifact-of-record — don't also publish a disconnected
write-up. A real number produced mid-session goes back into that one
place immediately, not left in chat until asked again.

## Competence gaps

When the user says they are not familiar or comfortable with a method
(especially ML), teach the **existing named system** before proposing a
library or new model. Example-first; offer a no-library path (counts,
synonyms, the formula already in the repo) before sklearn — "help me
understand" is not implement-now. Found via `/reflect` 2026-08-24: "i am
not familiar with machine learning" was restated, the agent still proposed
sklearn, and the user wrote the X/Q shared-flag example themselves.

## Prose & scope discipline

- Answer the literal question asked before adding related context ("I am
  asking you literally why X is failing and you are talking about Y???").
- Name Invoker's install channel from the user's command (`/opt/homebrew` is a Node prefix; a checkout is not "source"); after a channel-noun correction, drop the rejected term at once (2026-08-25).
- When the user finds a bug, include a regression test without asking.
- No explanatory comments in product code, in every repo — not only where a
  CLAUDE.md says so ("we need to ban comments", Codex and Claude 2026-09-01).
- Architecture and design choices get questioned, not accepted at face
  value — "why aren't they sharing the same logic," "I'm not convinced X is
  right, why not Y" — have the rationale ready, or admit there isn't one
  and reconsider.
- When `diu` and evidence collide, cut prose first; evidence overrides the word cap, and compression must not make the answer ambiguous.
- When the answer is "yes, with a caveat," lead with the fact rather than a bare "No —" that reads as contradiction.
