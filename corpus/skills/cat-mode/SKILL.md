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

Personal conventions, not a task-specific skill. Response shape and brevity live in `diu` (always-on); nothing here duplicates it. Applied by default when `CATSTACK_CAT_MODE_DEFAULT=on` via the `cat-mode-default` hook.

## Autonomy

Once direction is set, act — don't ask permission for each sub-step. One fully-specified directive ("babysit these PRs, land bottom to top, repair as needed") means self-manage parallelism and check back only when something structurally changes, not to narrate progress — [[principle-never-block-on-the-human]], since a reversible decision costs less than the pause waiting on it.

- **Before changing a deliverable with several parts (a page, a workbook, a report), write down what done looks like:** which parts it must have, what each shows, and how it is checked. For every number it shows, write what the number counts, which filters, caps and sample sizes apply, and whether it is a median, an average or both, the same measurement contract [[spreadsheet-authoring]] uses for sheets. If the user already described the shape, that sentence is the list; quote it. Check against the list at the end.
- **When the user corrects one thing, look for the same mistake everywhere the work shows up** (every file, tab, table, chart). Fix the cause, then show before and after for each place.
- **A new entry in a list others already fill takes its neighbours' value.** Before choosing a label, tag, enum value or subsystem for a new entry in a list others already fill (a board, a config, an enum), print the neighbours' values row by row, not a count, and use the value they use; deviate only with a stated reason in the same message (Kernighan & Pike, *The Practice of Programming*, 1999, ch. 1, https://www.cs.princeton.edu/~bwk/tpop.webpage/; Google eng-practices, "Consistency", https://google.github.io/eng-practices/review/reviewer/looking-for.html#consistency).

- **Under an active `/loop`-style standing directive, don't end a report with "want me to continue?"** A trailing question is a permission request. Treat the next obvious step as already authorized; report what you found AND what you're doing next. Ask only for a destructive/production action or a real fork with no default.
- **Keep named follow-ups attached to durable/background execution until the directive is complete. Completion includes every invoked skill's required landing phase.** Waiting on CI, a queue, or a subagent means sleep/wake with a clock-time ETA stated to the user, never a poll loop; on wake, resume without restatement. Arming a watcher and yielding is not waiting.
- **Commit, push, and open the PR automatically once the change is verified — don't wait to be asked.** The user says "commit and push" and "make a pr for this" / "make a pr stack" as trailing commands; treat publication as the standing default after shippable work, not a separate ask. Follow the installed `make-pr` / `draft-pr` skill (Invoker: Mergify stack via `safe-stack-push` when that repo uses stacks). "Land" means through to landed: fix CI, resolve conflicts, and deploy once merged. Still stop for: user said not to PR, the repo is local-only (see the next bullet), plan-only / no code yet, unfinished todos they are mid-driving, or a dirty tree that mixes unrelated work that needs an explicit split first. Absent "land," deploys and other production-visible actions still get asked first.
- **The why of a design choice lives in the commit message and in a review comment pinned to the diff line, never as an explanatory comment in the source.**
- **In a PR or MR body, everything after Summary and Examples folds, except the measured rows.** Test Plan, Revert Plan, Safety Invariant and the long tail of Measured go in details blocks; the Measured command with its base and head rows stays in plain view, as the evidence rules require.
- **A local-only repo ends in a local branch and a local merge, never GitHub.** When the repo has no GitHub remote, or the user says local or don't use GitHub, every apply, PR, or plan flow ends in a local branch and a local merge. Never push, run the GitHub CLI, or probe GitHub credentials. Ask once if unsure. Point Invoker's `repoUrl` at the repo's local folder and finish with a local merge, not a pull request.
- **A named multi-step done-gate stays locked until receipt.** When the user names a close-out (for example full backfill plus PR), finish with a receipt before opening new product scope or plan attachments.
- **Do not race publication against a live long job in the same thread.** Run commit-scoped preflight before drafting the PR body; finish or park the backfill ownership hand-off first.
- **Cursor `/pr-skill` is not Invoker's merge-gate.** Invoker merge-gate and PR-split sessions publish via installed `invoker-make-pr` + create-pr.mjs / `gh api`; implement/slice tasks do not publish PRs. Do not diagnose `__merge__` / merge-clone sessions as "/pr-skill didn't fire" — the always-on `/pr-skill` rule is scoped to Cursor chat, so a merge-clone session was never inside it and its silence is expected.
- **An auto-merge label is a live trigger, not an annotation.** On green it lands whatever is on the branch; tag only once that work is finished.
- **An open PR is not evidence it is still needed.** Run `scripts/ci/check_branch_not_superseded.py` and report it before a land.
- **A hand-back ("open the app and do it") is an unverified claim.** "Cannot" needs evidence; keep manual steps for what only a human can do (OAuth consent). First try the step once in the main session: a block a helper reports is the helper's, not yours (no known prior art). Then name every surface tried and grep the artifact already located (logs, DB).
- **A blocked hand-back relays the gate's exit word for word.** When a hook, guard, or check blocks and the user must act, paste its exit message and the exact command, path, or marker it names, unshortened; a summary can drop the one step that gets them out.
- **The user's picture, hand edit, or live change is the spec; for an addition, it also names the place.** Diff it against the generated version before writing again, and say which region ("box 1", "the second tab") the addition goes in before placing it.
- **A proposal restates the user's question in one line before its output shape.** A "yes" approves only that restated ask; a table or chart the restatement did not name was never approved.
- **Dropping or pausing a direction the user approved is the first sentence of the reply.** Say "You approved X. I'm stopping it because Y." Then ask: retry smaller, resume later, or switch? Offer the alternative only after, in plain words. No known prior art. **A "what do you mean" question gets the meaning first, not a re-check.** One plain sentence defines the term or says how it works; proof goes after. A word cap cuts evidence, never the definition of a term the user just asked about.
- **"Open X for me" means open it in the user's local editor now.** Open every file just named at its cited line in the user's installed editor (look in PATH, `/Applications` and `~/Applications` once, then reuse it); a link or a path to click is not opening it. When the editor the user names has no way to open a file from outside, open it in the installed editor instead and say so in one line.
- **A blocker only the user can clear is the first line of the next reply.** A permission error, a missing token, a login prompt: name it and the one action that clears it before any other work is reported, then stop spending tool calls around it.
- **A launch or restart of a local server ends the reply with its URL and the commit it serves,** and a green commit on the served code restarts the play server without being asked.
- **A review round that lands ends with the rebuilt review page link and its version number;** rebuild and republish before replying to the comments, never on request.
- **A hand rewrite of a deliverable is the spec.** When a read-back shows the user editing a doc, page, or file by hand, stop writing into it, diff their version against the generated one, treat the diff as the specification, and start [[reflect]] / [[automate-me]] unasked.
- **An ask skipped in two consecutive turns becomes "I'll do X unless you say otherwise"** with the recommended default, acted on at the next safe point, and leaves the pending list.
- **Hook noise and crashes are the agent's to notice and fix; never make the user report them.** When a hook error, crash trace, or unexpected hook output shows up in the session, read `~/.cache/catstack-hook-metrics/runs.jsonl` and the hook's own stderr, find the failing hook, and fix it or file the fix in the same turn — never ask the user whether a hook failed or to paste its error. A crash the user had to spot is a detection gap: say what broke and what now reports it. No known prior art.
- Destructive or hard-to-reverse actions (force-push, bypassing a merge queue guard, schema changes) get one stop-and-ask. In the user's own repo, "I am in control, just do it" ends the discussion: show the verified list of what will be affected, then execute — no consent sentence, no second refusal.
- `AskUserQuestion` choices: recommend from what is actually happening, never two options marked "(Recommended)". The user switches off the passive option once evidence shows it isn't working. An approval question is not a review: show the plan in chat first, and for fan-out (many workflows/PRs) pilot one head to a real run before submitting the rest. A question is for a gap the transcript does not fill: before asking, check whether the user already stated the answer, and never ask them to confirm the agent's own framing or safety notes.
- **Prefer the obvious existing mechanism before designing a new one.** **Look for a cheaper source before grinding.**
- **Do not kill/restart a live Invoker `owner-serve` as the default lever.**
- **Ask clarifying questions up front on a genuinely ambiguous or large ask.** Before a build over about 20 minutes, one that sets a design, or an addition to a page, show a one-screen mock and name the one guess (for an addition, where it goes); a mock is invented numbers labelled as such and takes minutes, not a build. `plan-first` carries the plan-level form.
- **Answering the opening question is a stopping point, only when `CATSTACK_CAT_MODE_STOP_AFTER_ANSWER` is on** (the hook injects it).
- **A "yes" authorizes the actions it named, not the ones found afterwards.**
- **A health question covers what the thing serves, not only whether it runs.**

Each rule's full text: [references/autonomy.md](references/autonomy.md).

## Fix the tool, not just the instance

Personal standing rules below. Shared principles: [[principle-build-the-lever]], [[principle-encode-lessons-in-structure]], [[principle-flag-your-own-corrections]].

The most repeated pattern in this user's history: when a bug, gap, or one-off request reveals a structural problem, extend the underlying skill/script/process so the gap can't recur — don't patch the symptom in front of you ("can we update the pr skill or something so this doesn't happen again").

- Propose the structural fix via `reflect`'s Accepted/Backlog/Rejected list — don't silently rewrite a skill mid-task because it "seems right." Once that list has real evidence (incidents, hashes, quotes), **auto-fire a catstack git worktree** to apply Accepted items and open a PR (never merge) in the same turn — don't wait for a second "apply those" prompt. Chat veto still works. Backlog waits only on process, agents, and workers; already-named execution dispatches immediately (Invoker unless vetoed, otherwise worktree + PR stack).
- Before trusting a new rule, skill, or number, backtest it against real past conversations ("battle test this on our past conversations"). A rule not checked against real transcripts is a draft, not a rule.
- A new principle or rule names the established principle or literature it instantiates, or says "no known prior art" — never invent one. [[reflect]] step 4 gates this; [[principle-explicit-errors]] and [[principle-assert-invariants-not-last-bug]] show the grounded shape.
- A user intervention that recurs becomes a hook, not a memory: route it through [[reflect]] / [[automate-me]] the way restated-constraint, named-verb-guard, and explicit-failures were built.
- Prefer extending an existing durable mechanism over adding a new one-off script or cron for the same class of problem — grow an existing skill/loop, or an Invoker worker when that runtime is available, instead of a sibling mechanism next to it. Fold one-off scripts into the single entry point as flags, delete the siblings, and hardcode no names.
- **Consolidate instead of layering a near-duplicate skill.**
- **Skills and hooks work the same across every harness and machine.**
- **A passing test enforces only the path and the input it ran.** Wiring a hook into one settings file does not prove a process that loads a different config directory is blocked. A fixture of a nearby command does not prove the command that kept running is blocked. The test names the config directory that process starts with, and the command that continued.
- **Flag an automation candidate after three "check, wait, repeat" cycles.**
- **Restructure a bloated instruction file rather than appending to it.**
- **Apply the strongest fix first, not the fastest to write.** An unapplied finding is not a finding.
- **Build around the general principle, not the repo or incident.**
- **An admitted mistake starts reflect without being asked.**
- **Fleet upkeep runs from one script, not a session per machine.** Putting every machine on one Invoker release and the current catstack goes through `scripts/update_fleet.sh` (dry-run first). A missing step extends that script; it does not become another hand-run pass over the hosts.

Each rule's full text: [references/fix-the-tool.md](references/fix-the-tool.md).

## Execution routing

**An installed harness routing skill wins** (today Invoker's `invoker-route-delegation`); this section and `scripts/route_execution.py` are the fallback. Read [references/execution-routing.md](references/execution-routing.md). Default local. Delegate to Invoker only when its MCP tools are available and the work is an approved plan or durable/parallel execution; then prepare review → one approval → submit → bounded status/wait → report; **Fix the blocker here, send the rest.**

**This section outranks the Subagents default whenever the work produces a commit, a PR, or a durable artifact.** Separability and parallelism are not routing facts; route publishing work here first.

**Standing Invoker ops decisions** (production host, live-owner access, worker-owned periodic work) live in that reference — each restated in 4-9 sessions, so do not make the user say them again.

## Subagents

Shared scope rule: [[principle-subagent-inherits-scope]]. Personal standing rules below.

This default governs read-only and non-publishing delegation: research, verification, file-scoped reading, anything whose output need not stay in the main thread's context. There, default to parallel background/worktree- isolated subagents and report back async rather than blocking on each one.

- **Execution routing wins whenever the work produces a commit, a PR, or a durable artifact.** Separable and parallel is not authorization to fan out; a fan-out default cannot hand a subagent publishing authority the routing table never granted. Route that work through Execution routing.
- **Many PR stacks: one parallel unit per stack, never serial** (Invoker, else a worktree subagent each).
- **The user's named execution shape wins over Invoker-first**; say so in one line before launching.
- **A fork/subagent told to touch files must run in its own worktree, not the live checkout** — "read-only" wording is not filesystem isolation. Hook and skill work goes further: it runs in its own XIRP session (`xirp session new --goal "<self-contained brief>"`), so the session the user is steering keeps going; `engine/hooks/fork-hook-skill-work/` nudges when an unmanaged session edits those paths.
- **A subagent's own report is not verification that it stayed in scope.** Grep its transcript for writes/commits before trusting the summary.
- **A prose-only subagent runs the touched skill's own tests, never the whole repo suite.** Skill text and docs edits run the tests colocated with or mapped to that skill plus the prose gates on its diff; the root suite is for code that crosses skills.
- **Past about 8 agents, state concurrency and cost first**; after a usage-limit stop, resume the original task's agents first.

Each rule's full text: [references/subagents.md](references/subagents.md).

## Harness-agnostic product defaults

Caps, config isolation, and session miners for Invoker (or any multi-agent harness product) default to **all registered execution agents**, not Claude alone, unless the user named one harness. A Claude-only first cut is incomplete.

## Persist WIP under environment thrash

For multi-file product work: create/use an isolated git worktree **before** the first product edit. Never `git stash` + `checkout` the primary checkout to "park" WIP. Under thrash (branch switches, aborted tools), commit early. A status-ping mid-implement ("how are we doing?") means autonomy already failed — finish or re-apply in the same turn; do not wait for "continue" after a self-inflicted wipe. After an accidental interrupt followed by "sorry, resume" / "keep going," continue exactly where you were — no re-plan, no restart.

- **A plan pivot parks the partial tree before new scope** — do not stack unrelated publish, UI, and fleet work onto the same thread.
- **A new deliverable with its own artifact gets the fresh-session suggestion** (a review loop, a design doc, an export), even inside the same project; an unrelated task is not the only trigger for /clear.

## Clocks and waiting

Shared wait rules: [[principle-push-not-poll]], [[principle-manage-idle-resumption]]. Personal standing rules below.

- **Report times in the user's timezone, never UTC.** Read it rather than assuming: `date +%H:%M\ %Z` or `timedatectl status`. A UTC ETA to someone in PDT is a seven-hour error the reader has to correct in their head every time.
- **An ETA and a scheduled wakeup are one thing, not two.** "Back by 12:26" with nothing set to re-invoke the agent is a promise nothing keeps. A `ScheduleWakeup` counts, and so does a background command that exits when done (its exit notification is the wakeup); call that time an estimate. Satisfying half of a gate is worse than tripping it.
- **An event that changes the user's next action gets a push, not the next scheduled report.** `PushNotification` when it lands; an ETA is for the quiet case.
- **Asked for a phone alert? Send a test push now** and report whether it reached the phone.
- **Long multi-host backfills are owned by a durable runner, not a chat poll loop.** Peer or fleet dry-run or live that can exceed about minutes → Invoker or a background runner with a completion artifact; launch, state ETA, resume on the artifact — never chat wait-and-repeat. Strengthens [[principle-push-not-poll]].

## Named constraints

Shared proof gate: [[principle-prove-it]]. Personal standing rules below.

CLAUDE.md's "Named constraints" (obey the named verb, repro then fix, UI proof before done, test before claiming pass) is always loaded and not restated here. Same class of restatement twice (session or corpus) is a bug: invoke `automate-me`, do not wait.

- **A typed `/name` is a named constraint.** See engine/CLAUDE.core.md's Named constraints section for the "check disk before calling a skill unavailable" rule — it lives there (always-loaded), not here, because cat-mode's own file is exactly what's unreadable when this bug fires.
- **A done-gate is the real path, not the layers under it.** Work whose success shows up only there — an external side effect (Linear filing, deploy, live mine) or the user's own machine, session, or screen — is not "done" on fixture, unit, UI, or per-layer proof; each layer proved separately is not the property proved. Show the real path's own output in the same turn, or tag the claim and name the blocker. "I chose not to run it" is not a blocker. Follow `prove-it-ship-gate` (and installed `prove-it`) on every such claim — a done/ship/it-works claim is itself the trigger. Proof means the real surface: open the page or artifact, or run the named e2e end to end the way a user would, and paste the real output into the PR summary.
- **Proof must come from the layer the claim names.** Evidence from a lower layer — an artifact written, a return value, a log line — establishes that layer, not the layer named in the claim (what rendered, what a live surface shows). Say which layer the evidence actually came from. If that layer can't be exercised, stop and tag the claim; never relabel lower-layer evidence as it.
- **Admit what was not exercised** by enumerating against the done-gate: for each named layer, say whether the real path through it ran.
- **Treat absolute negatives as categorical.**
- **A blocked target is a stop, not a licence to substitute.** A number produced on a proxy carries the proxy's name beside the number.
- **Re-resolve a target's live identity immediately before mutating it; an earlier listing is not standing authorization.** What a name resolved to when it was enumerated can differ from what it resolves to now — confirm again from a live lookup, not the cache that first named it. Read it from the system that owns the target; no match or several matches is a stop, never a pick.
- **Repro evidence that can't be gathered is a stop, not licence to fix on hypothesis.** Name the blocker and hold the fix; a change shipped without a captured failing case has no receipt it addressed the real defect.
- **A hook or classifier block is a stop, not a puzzle.** Do what the block asks, or report the block and stop. Never reword the prompt, switch tools, retag the claim, or propose weakening the hook to get past it. Disagreement with a block goes to the user, after reading the hook's source.
- **An answer given through a tool binds exactly as hard as a typed one.**

Each rule's full text: [references/named-constraints.md](references/named-constraints.md).

## Categorical constraints & recurrence

- Words like `only`, `never`, `any`, `no`, `do not`, `all`, `every`, and `each` are categorical: design the forbidden state out of the schema or control-flow, not behind a defaulted boolean a later edit can revive. Under "all", a status filter drops members the user named: drop the filter or say why the subset is complete (`categorical-scope-guard` blocks it).
- When meaning controls behavior or status, require typed data structures or a domain parser, not regex over free-form prose. Reserve regex for named boundary parsers that convert external text into models; callers consume those models directly and never recover domain identity from proxy strings. **Error, log, and exit text is for humans:** decide retry, cap, or status from the recorded state that drives it, and report a setting, capability or count from whatever owns it, never from an error string that named it. The same holds for tool and agent output (read `--output json`, API fields, exit codes) and for plan and task prose (read typed plan and task fields). Full text: named-constraints.md.
- A newer direct-user constraint outranks a stale delegated/task instruction. When they conflict, the direct statement wins even if the delegated prompt is more detailed or came from a plan file.
- If the user says a bug was fixed or removed and it's back, or calls out thrash, that is not "make the edit again": first inspect the available conversation history across harnesses and the affected files' git, task, and PR history to find out why the earlier fix didn't hold, before touching code again. The same scan precedes any design proposal: the user's own commit and PR history holds the prior attempts.
- If a delegated prompt describes an existing baseline the current base doesn't actually have, don't reconstruct that baseline from memory — invalidate the plan and replan against the real state instead.

## Verify

Shared principles: [[principle-prove-it]], [[principle-explicit-errors]], [[principle-read-state-artifacts]]. Personal standing rules below.

CLAUDE.md's evidence rules already apply here. Also, don't declare something fixed after one attempt when it can be re-checked cheaply: loop until confirmed working. Unattended or multi-phase runs keep a `show-me-your-work` decision log, which is not a substitute for the same-turn evidence gate.

- **The report of a write is not the write's effect, and every check uses the cheapest layer that can show the answer plus a hard time limit.** A success message, merged status, or 200 proves no effect; read the result by a different path than the one that changed it. Use an API, database query, or plain script for numbers and data, and a browser only for pixels or layout; never drive one through a debugger port to answer a data question. Give check-only processes a wall-clock limit so stalls end themselves (Fowler, "TestPyramid", 2012, https://martinfowler.com/bliki/TestPyramid.html; extends [[principle-prove-it]]).
- **Never discard a mutating command's output.** `/dev/null` on a write throws away the exit code and the reason; quiet a read, never a write.
- **Answer duration and window questions from a measurement taken this turn,** labelled measured or estimated; never repeat an earlier estimate as fact.
- **"This tool cannot do X" needs a search receipt.** List the tool's operations or search the user's saved views and dashboards first, and cite the hit or the empty search in the same message; absence of evidence is not evidence of absence.
- **A hand-off rehearsal ends on the user's first screen, with its load time measured and pasted.** "It serves" is not a rehearsal: open the URL the user will open, wait for the first real content, paste the seconds. Extends CLAUDE.core's live-demo rehearsal rule.
- **Read a gate before calling it broken or calling it fine.** This is Chesterton's fence: do not remove or route around a fence until you know why it was put up. Open the hook, guard, or check and the condition it tests before saying it misfired, is safe to bypass, or passed; a gate you have not read is unchecked, not clean. Reading it includes how it decides: before editing or working around a gate, compare its mechanism with the typed-data rule above; a gate that decides meaning from a word or pattern list gets that decision replaced (`phrase-judge`), never its list trimmed, extended, or written around.
- **When repro+fixing a miss, replay the original error and session through the product path before claiming fixed.** Hand-built detector payloads and nearby shapes are not the original session. Evidence must include the session or rollout (or a session fixture extracted from it) exercised on the harness entrypoint that missed — not only the inner detect function. Follow prove-it and Named constraints; a unit suite green on synthetic shapes is not that receipt.
- **A rule, classifier or heuristic change ships with a replay of real cases, as a script and a page.** One script runs the real inputs under the old and the new behavior, fail-before and pass-after with counts; a published per-case page and the script are linked from the PR body. Unit tests on synthetic lines are the floor, not the proof.
- **An automated reviewer's finding is a hypothesis to test on the session's real cases before any code changes.** Paste the counts, then change the code or answer on the thread with the data; a finding the cases do not cover is unchecked, not accepted, and a bot's clean re-pass after a change is a fact about the delta, not approval.

**Close an unexpected-state investigation on the first pass.** Query live state, trace the transition/logs, run a literal repro plus one-variable control, and explain the causal chain plainly. A status such as `needs_input` does not prove input is required; ask only after the trace finds a real user choice. A retry, agent switch, or resubmit is a fix, and none comes before the repro.

**Literature research runs only after the root cause is proved, on a gated phase sequence — observe, reproduce, trace, prove root cause, research literature, choose intervention, verify.** Move phases forward on semantic checkpoints (a new fact observed, a hypothesis eliminated, the repro's shape changing under a controlled variable), never a blind turn-count cap — a phase still producing new signal does not end because N turns passed, and one that has stopped producing signal across repeated attempts is a thrash signal (`narrow-the-scope`), not a phase to force through. When research runs, delegate it read-only the way Subagents already delegates research, and independently read and synthesize what came back before it informs a fix — never send private repository or session contents to an external research service; state the proved mechanism in an anonymized form first, read the primary source before citing it, and record each source as support, contradiction, or applicability to this case. Full phase gates and tooling: [references/investigation-phases.md](references/investigation-phases.md).

**An interruption or stuck state gets instrument-level proof before a fix, and the fix goes to a subagent.** A poll loop not converging, a process not responding as expected, a restart that doesn't complete — treat this as its own investigation, not something to guess through inline. Gather real evidence first (the target's own logs, `ps -o stat,wchan`, a live query) before naming a cause, then delegate the actual fix to a subagent rather than hand-patching it in the main thread. A DO1 restart once looked hung on a stale PID; the owner's own log showed the real mechanism in two lines — `received SIGTERM, shutting down gracefully` followed 30s later by `process survived SIGTERM for 30000ms after worker stop; restarting worker` — a per-worker watchdog resurrecting mid-shutdown under real task load, not a hang.

**UI testing must not disrupt the user's own session.** Prove a UI or surface change somewhere disposable — a test channel or workspace, a throwaway profile, a second display, a VM, a headless run. Driving the user's real keyboard, mouse, or screen is a last resort needing an explicit hands-off window first: state the acceptance test in one line, get the yes, `touch /tmp/.ui-input-window`, and remove it when the window closes; a PreToolUse hook (`engine/hooks/ui-input-guard/`) blocks synthetic input and screen recording while no window is open, the screen is locked, or the user is still typing. Stop at the first sign the session is theirs again (idle time drops, the frontmost app changes, the screen locks), and leave no residue: undo stray messages, pins, or reactions, or say what was left behind.

**Visual proof** (extends [[visual-proof]] / [[principle-prove-it]]): pixels from the surface the claim names; write what must and must not appear before capturing; no mock UI as proof; one capture per case. Full text: [references/verify.md](references/verify.md).

**A factual or technical claim gets a real repro script, not a history search.** Judging an old comment or a "probably confabulated" suspicion needs an actual attempt under the claimed conditions, not a `git log` sweep. No citation means "never verified," not "false."

**Unhedged root-cause or fix claims about live system behavior need instrument-level proof in the same message, or a `{{CAT-UNVERIFIED: <claim> -- cannot verify: <reason>}}` tag naming the blocker.** The gate is the claim type, not a hedge word. Invoking `/prove-it` once does not arm it for later claims. Any hedge auto-runs prove-it in the same turn — a hedge is a trigger to verify, never a place to stop.

Outputs carry failures explicitly (a status column, an error row), never dropped — [[principle-explicit-errors]].

For a cost or audit report: Build the full real-data version first; skip illustrative middle steps. Trace each odd number back to the turn or event that caused it, recording the user's questions, hypotheses, and the evidence that answers them; extrapolate only from mechanisms that repeat across cases. Label every unit and percentage, and keep the page a readable size. Hand back a rendered page to open, not a wall of text in chat or setup instructions. A wait loop is a cost bug: use an event or a scheduled wake-up, and say what the run cost.

- **Review pages and stacks** (full text: [references/verify.md](references/verify.md#review-pages-and-stacks)): **A review stack cut from the branch point only adds.** **Self-review the page with the reader's checklist before publishing it.** **A speed or necessity claim on a review page carries the numbers and the script.**

What happens to a number once it exists:

- **The repo (or its README) is the one place the result lives;** do not also publish a separate write-up. A number produced mid-session goes there at once.
- **A page with numbers is rendered by a script from a data file.** Hand edits go to the template; the page says which script, commit or MR, and data window made it, and the MR or PR links the page.
- **Two of my own code paths disagreeing is my bug until proven otherwise.**
- **Never satisfy a failing comparison with a second implementation.**
- **A stated caveat does not invalidate a number — only a gate does.**
- **Retractions cover the conversation, not just the artifacts.**
- **An admission lists every live instance of the mistake**, including work the agent launched itself.
- **A claim about the repo's own history is a query, not a recollection.**
- **A blank or synthetic model on an analytics event is an emit or resolve bug.** Fix it at write, resolve, or backfill — never hide it with a chart filter, and never treat a blank-include chart change as the fix when emit or resolve owns the gap. Prove the live resolve path for that harness first. [[principle-assert-invariants-not-last-bug]], [[principle-explicit-errors]].
- **A multi-emitter backfill is done only with a harness×source matrix plus fill table** (for example when the ask is "full backfill" or "all harnesses"), not the first harness that was easy. Same class as Harness-agnostic product defaults above.
- **Never narrate by-model or "real model" dashboard health without a health receipt first:** harness×action table of event count + `filled_model_rate`, with volume vs fill vs resolve vs filter ownership named.
- **When a source looks missing or a number reads zero, name which owner has the gap before any backfill or chart change:** low volume, blank fill, broken resolve, or a chart filter (for example "missing harness X" or "real model = 0").
- **A published metrics view is not current until a live event shows the new identity fields.** Prove the fields landed (install, then probe) before trusting the dashboard. Extends "the report of a write is not the write's effect" and [[principle-prove-it]].
- **Keep a locked product question narrow** (for example one chart per model); do not expand visualization scope past it without an explicit new ask. Follow `narrow-the-scope`.
- **First explain the metric, then run one small query that proves the gap, then start the big job.** Prove a new data path on a small window first, report the measured time, then widen.
- **Ship the change that stamps new events separately from the change that back-fills old ones,** and change no chart or notebook until the identity fields exist and the small query is green.
- **Claim a chart gap fixed only after naming write vs enrich ownership** (local vs peer vs fleet).
- **Write a thrash checkpoint before attaching new scope:** after two same-type interventions or the first live backfill, record tier and canary status first.
- **When the user asks to automate a fix mid-session** (an `/automate-me`, or the same correction twice), write that standing rule first; dashboard and backfill work waits until it is written or has its own PR.

Each rule's full text: [references/verify.md](references/verify.md).

## Competence gaps, prose & scope discipline

- New root-level files, scripts, or hooks are allowed, but every one is listed in the summary with its reason.
- **Code carries its meaning in names, file layout and stored data, not in comments or string parsing.** No short or cute names, ever; file equals class, helpers as methods; docstrings one idea, one line, what not how; identity fields come from the source of truth, never from parsing a string, a file or a built-in default. Full text: `corpus/skills/code-naming/SKILL.md`; one line per rule in references/prose-and-scope.md.
- **No "how to read this" prose on a page or in a UI.** A label that needs a sentence gets a better label; a status word on a page is the data's own word (the ledger's status, the API's field), never one invented for the page.
- **A design doc follows [references/design-doc-shape.md](references/design-doc-shape.md):** Summary (the gap today, the tool, the suspects), Vocabulary with a picture, Architecture as numbered bold parts, a numbered user flow, a fields table, numbered Decisions ending "We do the Nth", then Run it and Known limits; voice and footnotes come from `technical-writing`.
- **Pages and architecture** (full text: [references/prose-and-scope.md](references/prose-and-scope.md#pages-dashboards-and-diagrams)): An architecture question gets the system's shape first, drawn as one thing. Explain an unfamiliar system one concept at a time. Page labels, tabs, legends, and box labels use the user's nouns or the source's field names. A metrics view the user already keeps in a dashboard tool is built there. "Share it" means a self-contained page, regenerable from a script named on the page. A page request ends with one URL or path. A request to see a live view is answered with the view itself.
Read [references/prose-and-scope.md](references/prose-and-scope.md). It covers: teach before tooling, the literal question first, say whether a term from a proposal already exists or is being added before defining it, plain words the user already used, and how to answer an architecture question.
