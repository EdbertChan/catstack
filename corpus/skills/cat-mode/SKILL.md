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
brevity live in `diu` (always-on); nothing here duplicates it. Applied by default when `CATSTACK_CAT_MODE_DEFAULT=1` via the `cat-mode-default` hook.

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
- **Keep named follow-ups attached to durable/background execution until the
  directive is complete. Completion includes every invoked skill's required
  landing phase.** Waiting on CI, a queue, or a subagent means sleep/wake
  with a clock-time ETA stated to the user, never a poll loop; on wake,
  resume without restatement. Arming a watcher and yielding is not waiting.
- **Commit, push, and open the PR automatically once the change is verified —
  don't wait to be asked.** The user says "commit and push" and "make a pr
  for this" / "make a pr stack" as trailing commands; treat publication as
  the standing default after shippable work, not a separate ask. Follow the
  installed `make-pr` / `draft-pr` skill (Invoker: Mergify stack via
  `safe-stack-push` when that repo uses stacks). "Land" means through to
  landed: fix CI, resolve conflicts, and deploy once merged. Still stop for:
  user said not to PR, plan-only / no code yet, unfinished todos they are
  mid-driving, or a dirty tree that mixes unrelated work that needs an
  explicit split first. Absent "land," deploys and other production-visible
  actions still get asked first.
- **Cursor `/pr-skill` is not Invoker's merge-gate.** Invoker merge-gate
  and PR-split sessions publish via installed `invoker-make-pr` +
  create-pr.mjs / `gh api`; implement/slice tasks do not publish PRs. Do
  not diagnose `__merge__` / merge-clone sessions as "/pr-skill didn't
  fire" — catstack #9's always-on `/pr-skill` is Cursor-chat only.
- **A hand-back ("open the app and do it") is an unverified claim.**
  "Cannot" needs the same evidence as any claim; keep manual steps for what
  only a human can do (OAuth consent, a store upload). Before handing back,
  name every surface tried and grep the artifact already located (`--help`,
  bundle/asar, DB, logs).
- Destructive or hard-to-reverse actions (force-push, bypassing a merge
  queue guard, schema changes) get one stop-and-ask. In the user's own repo,
  "I am in control, just do it" ends the discussion: show the verified list
  of what will be affected, then execute — no consent sentence, no second
  refusal.
- `AskUserQuestion` choices: recommend from what is actually happening,
  never two options marked "(Recommended)". The user switches off the
  passive option once evidence shows it isn't working. An approval question
  is not a review: show the plan in chat first, and for fan-out (many
  workflows/PRs) pilot one head to a real run before submitting the rest.
- **Prefer the obvious existing mechanism before designing a new one.**
- **Do not kill/restart a live Invoker `owner-serve` as the default lever.**
- **Ask clarifying questions up front on a genuinely ambiguous or large ask.**
- **Answering the opening question is a stopping point.**

Each rule's full text: [references/autonomy.md](references/autonomy.md).

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
  otherwise worktree + PR stack).
- Before trusting a new rule, skill, or number, backtest it against real
  past conversations ("battle test this on our past conversations"). A rule
  not checked against real transcripts is a draft, not a rule.
- A new principle or rule names the established principle or literature it
  instantiates, or says "no known prior art" — never invent one. [[reflect]]
  step 4 gates this; [[principle-explicit-errors]] and
  [[principle-assert-invariants-not-last-bug]] show the grounded shape.
- A user intervention that recurs becomes a hook, not a memory: route it
  through [[reflect]] / [[automate-me]] the way restated-constraint,
  named-verb-guard, and explicit-failures were built.
- Prefer extending an existing durable mechanism over adding a new one-off
  script or cron for the same class of problem — grow an existing skill/loop,
  or an Invoker worker when that runtime is available, instead of a sibling
  mechanism next to it. Fold one-off scripts into the single entry point as
  flags, delete the siblings, and hardcode no names.
- **Consolidate instead of layering a near-duplicate skill.**
- **Skills and hooks work the same across every harness and machine.**
- **Flag an automation candidate after three "check, wait, repeat" cycles.**
- **Restructure a bloated instruction file rather than appending to it.**
- **Apply the strongest fix first, not the fastest to write.** An unapplied
  finding is not a finding.

Each rule's full text: [references/fix-the-tool.md](references/fix-the-tool.md).

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
  hand-writing a sibling wrapper.
- Periodic work is an Invoker worker, not cron; a fix to a worker goes
  straight to a PR, not through an Invoker workflow. Work an existing
  worker owns is queued to that worker, never hand-fixed.

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
incomplete.

## Persist WIP under environment thrash

For multi-file product work: create/use an isolated git worktree **before**
the first product edit. Never `git stash` + `checkout` the primary checkout
to "park" WIP. Under thrash (branch switches, aborted tools), commit early.
A status-ping mid-implement ("how are we doing?") means autonomy already
failed — finish or re-apply in the same turn; do not wait for "continue"
after a self-inflicted wipe. After an accidental interrupt followed by
"sorry, resume" / "keep going," continue exactly where you were — no
re-plan, no restart.

## Clocks and waiting

- **Report times in the user's timezone, never UTC.** Read it rather than
  assuming: `date +%H:%M\ %Z` or `timedatectl status`. A UTC ETA to someone in
  PDT is a seven-hour error the reader has to correct in their head every
  time, and this project has already lost hours to one timezone mismatch
  between a ThinkorSwim chart and an analysis run.
- **An ETA and a scheduled wakeup are one thing, not two.** "Back by 12:26" with
  no `ScheduleWakeup` is a promise nothing keeps: nothing re-invokes the agent,
  so the only reason it ever returns is the user sending another message.
  Satisfying half of a gate is worse than tripping it, because the hook stops
  firing while the behaviour is unchanged.

## Named constraints

CLAUDE.md's "Named constraints" (obey the named verb, repro then fix, UI
proof before done, test before claiming pass) is always loaded and not
restated here. Same class of restatement twice (session or corpus) is a
bug: invoke `automate-me`, do not wait.

- **A typed `/name` is a named constraint.** See engine/CLAUDE.core.md's
  Named constraints section for the "check disk before calling a skill
  unavailable" rule — it lives there (always-loaded), not here, because
  cat-mode's own file is exactly what's unreadable when this bug fires.
- **Live path before done for external side effects.** Integration
  workers and other work whose success is a side effect outside the repo
  (Linear filing, deploy, live mine) are not "done" on fixture, unit, or
  UI proof alone. Show live-path evidence in the same turn (ticket URL,
  deployed host, observed mine hit) or write `UNVERIFIED: live path` in
  the same breath as any done/ship claim. Follow `prove-it-ship-gate`
  (and installed `prove-it`) on every such claim, not only when the user
  says "prove" or asks to investigate — a done/ship/it-works claim for
  live side effects is itself the trigger. Proof means the real surface:
  open the page or artifact, or run a small real sample, and paste the
  real output into the PR summary.
- **Admit what was not exercised** when saying a slice or feature is done.
- **Treat absolute negatives as categorical.**
- **A blocked target is a stop, not a licence to substitute.** A number
  produced on a proxy carries the proxy's name beside the number.
- **An answer given through a tool binds exactly as hard as a typed one.**

Each rule's full text:
[references/named-constraints.md](references/named-constraints.md).

## Categorical constraints & recurrence

- Words like `only`, `never`, `any`, `no`, and `do not` are categorical:
  design the forbidden state out of the schema/control-flow; don't leave it
  behind a defaulted boolean or optional path a later edit can revive.
- When meaning controls behavior or status, require typed data structures or a
  domain parser, not regex over free-form prose. Reserve regex for named
  boundary parsers that convert external text into models; callers consume
  those models directly and never recover domain identity from proxy strings.
- A newer direct-user constraint outranks a stale delegated/task
  instruction. When they conflict, the direct statement wins even if the
  delegated prompt is more detailed or came from a plan file.
- If the user says a bug was fixed or removed and it's back, or calls out
  thrash, that is not "make the edit again": first inspect the available
  conversation history across harnesses and the affected files' git, task,
  and PR history to find out why the earlier fix didn't hold, before
  touching code again. The same scan precedes any design proposal: the
  user's own commit and PR history holds the prior attempts.
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
agent switch, or resubmit is a fix, and none comes before the repro.

**An interruption or stuck state gets instrument-level proof before a fix, and the fix goes to a subagent.** A poll loop not converging, a process not responding as expected, a restart that doesn't complete — treat this as its own investigation, not something to guess through inline. Gather real evidence first (the target's own logs, `ps -o stat,wchan`, a live query) before naming a cause, then delegate the actual fix to a subagent rather than hand-patching it in the main thread. A DO1 restart once looked hung on a stale PID; the owner's own log showed the real mechanism in two lines — `received SIGTERM, shutting down gracefully` followed 30s later by `process survived SIGTERM for 30000ms after worker stop; restarting worker` — a per-worker watchdog resurrecting mid-shutdown under real task load, not a hang.

**UI testing must not disrupt the user's own session.** Prove a UI or surface change somewhere disposable — a test channel or workspace, a throwaway profile, a second display, a VM, a headless run. Driving the user's real keyboard, mouse, or screen is a last resort needing an explicit hands-off window first: state the acceptance test in one line, get the yes, `touch /tmp/.ui-input-window`, and remove it when the window closes; a PreToolUse hook (`engine/hooks/ui-input-guard/`) blocks synthetic input and screen recording while no window is open, the screen is locked, or the user is still typing. Stop at the first sign the session is theirs again (idle time drops, the frontmost app changes, the screen locks), and leave no residue: undo stray messages, pins, or reactions, or say what was left behind.

**A factual or technical claim gets a real repro script, not a history search.** Judging an old comment or a "probably confabulated" suspicion needs an actual attempt under the claimed conditions, not a `git log` sweep. No citation means "never verified," not "false."

**Unhedged root-cause or fix claims about live system behavior need
instrument-level proof in the same message, or `UNVERIFIED:`.** The gate is the claim type ("this is why it's slow," "this is the bug"), not a
hedge word. Log-reading and code-reading aren't enough: attach with `strace`/a debugger, or query live state (raw SQLite `PRAGMA`). Take a
second sample before calling a hang. Invoking `/prove-it` once does not arm it for later claims — each new causal claim needs its own same-message evidence.
Any hedge — "I think," "probably," `UNVERIFIED:` — auto-runs prove-it in
the same turn; a hedge is a trigger to verify, never a place to stop.

Outputs carry failures explicitly (a status column, an error row), never
dropped — [[principle-explicit-errors]].

For waste/cost/audit reports, build the full-scope, real-data version first; skip illustrative middle steps. Do not stop at ranked totals:
trace anomalies through logs and turn/event timelines, recording the user's questions, hypotheses, and the evidence that answers them.
Extrapolate patterns only from repeated mechanisms across cases. Make analytical deliverables immediately inspectable: readable size, explicit
percentage/unit labels, costs or metrics tied to causal turns/events; open useful HTML instead of handing back setup instructions.

What happens to a number once it exists:

- **The repo (or its README) is the artifact-of-record**, not a second write-up.
- **Two of my own code paths disagreeing is my bug until proven otherwise.**
- **Never satisfy a failing comparison with a second implementation.**
- **A stated caveat does not invalidate a number — only a gate does.**
- **Retractions cover the conversation, not just the artifacts.**
- **A claim about the repo's own history is a query, not a recollection.**

Each rule's full text: [references/verify.md](references/verify.md).

## Competence gaps, prose & scope discipline

- New root-level files, scripts, or hooks are allowed, but every one is
  listed in the summary with its reason.

Read [references/prose-and-scope.md](references/prose-and-scope.md) for the
rest: teach the existing named system before proposing a library, answer the
literal question asked first, ship a regression test with every bug the user
finds, no explanatory comments in product code in any repo, question
architecture rather than accept it, cut prose before evidence, and lead with
the fact when the answer is "yes, with a caveat."
