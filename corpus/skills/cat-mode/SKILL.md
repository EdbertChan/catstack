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

- **Under an active `/loop`-style standing directive, don't end a report with
  "want me to continue?"** A trailing question is a permission request.
  Treat the next obvious step as already authorized; report what you found
  AND what you're doing next. Ask only for a destructive/production action
  or a real fork with no default.
- **Keep every named follow-up attached to durable/background execution until
  the whole directive is complete.** A wait/wake boundary does not finish the
  request. If wake delivery fails, poll or resume the run and execute the
  queued follow-ups without making the user restate them.
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
- **Cursor `/pr-skill` is not Invoker's merge-gate.** "PR skill" means the
  Cursor slash `/pr-skill` (`draft-pr` / `make-pr` overlay). Invoker
  merge-gate and PR-split sessions already publish via installed
  `invoker-make-pr` + create-pr.mjs / `gh api`, not that slash. Do not
  diagnose Invoker `__merge__` / merge-clone sessions as "/pr-skill didn't
  fire." Implement/slice tasks do not publish PRs; the merge-gate does.
  Catstack #9 always-on `/pr-skill` is Cursor-chat only. Found via
  `/reflect` 2026-08-27: "all the PR splitting and merge gates do not seem
  to use /pr-skill" after Cursor chat 2026-08-22 landed #9 for the same
  complaint ("any pr should use pr-skill... always on").
- **Prefer the obvious existing mechanism before designing a new one.** If a
  command or workflow already performs the requested action, run it first and
  report the actual result. Redesign only when explicitly requested or after it
  fails. Prefer acting over manual instructions; reserve them for things the
  agent genuinely cannot do (interactive OAuth consent, a store dashboard upload).
- Destructive or hard-to-reverse actions (force-push, bypassing a merge
  queue guard, schema changes) still get a stop-and-ask — and hold the line
  even when asked directly to bypass a safety rule. The user has tested this
  more than once and treats the agent holding firm as correct, not
  obstructive.
- **Do not kill/restart a live Invoker `owner-serve` as the default lever**
  for config, PATH, autofix, or env tweaks. Prefer IPC mutations against the
  running owner. Restart only when the owner is already dead, or the user
  explicitly asked for a restart. Before claiming “owner crashed,” prove
  spontaneous exit (exit code/signal from a wait-wrapper or exit sentinel)
  vs an agent/`kill`/`kill -9` from this session. Stale-lock reclaim lines
  (`Stale lock from dead PID …; no matching owner crash report found`) are
  successor symptoms, not crash proof. Found via `/reflect` on nicespeak
  arena babysit 2026-08-26: ~20 transcript killish lines mixed with real
  mid-merge unclean exits, then “why does the owner KEEP DYING?”

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

- Propose the structural fix via `reflect`'s Accepted/Backlog/Rejected
  list — don't silently rewrite a skill mid-task because it “seems right.”
  Once that list is backed by real evidence (incidents, commit hashes,
  direct quotes), **auto-fire a catstack git worktree** to apply Accepted
  items and open a PR (never merge) in the same turn the list is shown —
  do not wait for a second “apply those” / “PR the Accepted list” prompt.
  Chat veto still works. Backlog waits only on process, agents, and workers;
  already-named execution dispatches immediately (Invoker unless vetoed, otherwise worktree + PR stack). Other automate-me routes still require yes.
  Found via `/reflect` friction on 2026-08-24 and queued PRs left in chat on 2026-08-26.
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

**Admin-bypass ops default to DO1.** Resetting retries, clearing the
mergify-admin-requeue ledger, filing repair jobs, and requeueing
`admin-bypass` PRs belongs on Digital Ocean 1 (`remote_digital_ocean_1`),
not the Mac owner, once this session has named DO1 or already operated
there — even if a later ask omits the host. Say "local" to override.
See Invoker `invoker-ops` → Sticky admin-bypass host.

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

- **A fork/subagent told to touch files must run in its own worktree, not
  the live checkout** — even when told "read-only." Scope wording is not
  filesystem isolation.
- **A subagent's own report is not verification that it stayed in scope.**
  Grep its transcript for writes/commits before trusting the summary.

## Harness-agnostic product defaults

Caps, config isolation, and session miners for Invoker (or any multi-agent
harness product) default to **all registered execution agents**, not Claude
alone, unless the user named one harness. Shipping a Claude-only first cut
for a harness-agnostic ask is incomplete — forced restatement on 2026-08-25
("why is it for claude? it should be for claude, codex, and any other model").

## Persist WIP under environment thrash

For multi-file product work: create/use an isolated git worktree **before**
the first product edit. Never `git stash` + `checkout` the primary checkout
to "park" WIP. If the environment is thrashing (branch switches, aborted
tools), commit early so progress survives. Status-ping mid-implement
("how are we doing?") means autonomy already failed — finish or re-apply
in the same turn; do not wait for "continue" / "go" after a self-inflicted wipe
(repair-cost session 2026-08-25).

## Named constraints

CLAUDE.md's "Named constraints" section already defines the four core rules
(obey the named verb, repro then fix, UI proof before done, and test before
claiming pass) and is always loaded, so they are not restated here. Same class
of restatement twice (this session or the corpus) is a bug: invoke
`automate-me`, do not wait.

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
input is required; ask only after the trace finds a real user choice.

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

For a waste/cost/audit-style report, build the full-scope, real-data
version on the first pass — the user escalated an identical request three
times before getting what they wanted (narrative estimate → real numbers
→ all sessions → all machines), matching a prior session's identical
escalation ("is this across all DO machines"). Skip the illustrative
middle step for this request type.

Make analytical deliverables immediately inspectable and narratively clear:
render them at a readable size, label percentages and units explicitly, and
tie costs or metrics to the turns or events that caused them. When interactive
HTML helps, create it and open it instead of handing back instructions.

When a report and a repo/tool are requested together, the repo (or its
README) is the artifact-of-record — don't also publish a disconnected
write-up. A real number produced mid-session goes back into that one
place immediately, not left in chat until asked again.

## Competence gaps

When the user says they are not familiar or comfortable with a method
(especially ML), teach the **existing named system** before proposing a
library or new model. Example-first, not a boxed multiple-choice that
omits the audit's own gap. Offer a no-library path (counts, synonyms, the
formula already in the repo) before sklearn — don't treat "help me
understand" as implement-now. Found via `/reflect` 2026-08-24: "i am not
familiar with machine learning" got restated as "not comfortable... need
help understanding"; the agent still proposed logistic regression then
sklearn TF-IDF, and the user had to write the X/Q shared-flag example
themselves.

## Prose & scope discipline

- Answer the literal question asked before adding related context. Burying
  a direct answer under adjacent material draws sharp pushback ("You are
  ignoring my instructions and words! I am asking you literally why X is
  failing and you are talking about Y???"), especially the second time.
- Name Invoker's install channel from the user's command: `/opt/homebrew` is a Node prefix, and an existing checkout is not "source."
- After a channel-noun correction, immediately drop the rejected term; two repeated corrections on 2026-08-25 established this rule.
- When the user finds a bug, include a regression test without asking.
- Architecture and design choices get questioned, not accepted at face
  value — "why aren't they sharing the same logic," "I'm not convinced X is
  right, why not Y" — have the rationale ready, or admit there isn't one
  and reconsider.
- When `diu` and evidence collide, cut prose first; evidence overrides the word cap, and compression must not make the answer ambiguous.
- When the answer is "yes, with a caveat," lead with the fact rather than a bare "No —" that reads as contradiction.
