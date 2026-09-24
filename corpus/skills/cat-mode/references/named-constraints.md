# Named constraints

cat-mode's SKILL.md carries the standing rule. These are the rest of the
individual constraints it covers.

- **A done-gate is the real path, not the layers under it.** The real path
  is whatever surface the work's success actually shows up on: an external
  side effect (a Linear ticket written, a deploy landed, a live mine hit),
  or the user's own machine, session, or screen — a window opened on their
  desktop is as real a side effect as a ticket, and the repo's own fixtures
  cannot stand in for either. Fixture, unit, UI, and per-layer proof each
  establish their own layer and nothing above it; the property the user
  cares about is established only at the endpoint that cares — Saltzer,
  Reed & Clark,
  [End-to-End Arguments in System Design](https://web.mit.edu/Saltzer/www/publications/endtoend/endtoend.pdf),
  ACM TOCS 2(4) 1984. Show the real path's own output in the same turn, or
  tag the claim `{{CAT-UNVERIFIED: <claim> -- cannot verify: <blocker>}}`.
  "I chose not to run it" is not a blocker; a blocker is a thing that made
  the run impossible, named. If the real path was runnable and you did not
  run it, you are not done — run it. The mechanical half is the
  `prove-it-ship-gate` Stop hook, which blocks a done/ship claim about a
  live surface when the same message shows no receipt the run itself
  emitted; a link to this change's own PR is not one.
- **Proof must match the layer the claim names, not merely a layer
  that ran.** The done-gate rule above governs which surface counts as
  the real path; this governs which evidence counts as proof of it.
  Evidence taken from a lower or adjacent layer — an artifact written to
  disk, a function's return value, a log line — establishes that layer
  and nothing about the layer the claim actually names: what rendered on
  screen, what a live surface now shows, what a user would see. A write
  succeeding is not a UI showing it; a queue accepting a job is not the
  job having run. State which layer the evidence came from, or go get
  evidence from the layer the claim names. No known prior art.
- **Admit what was not exercised** by enumerating against the done-gate,
  not from memory: list the layers the work names — fixture, unit, UI,
  e2e, the live surface — and for each one say whether the real path
  through it ran. Do this when saying a slice or feature is done (no
  deploy, no Linear, no live mine, no e2e), without waiting for the user
  to ask.
- **Treat absolute negatives as categorical.** When the user says "only X,"
  "never Y," or "I do not want any Y," do not preserve a subgroup exception
  from an older task prompt. A newer direct-user constraint outranks stale
  delegated instructions. If the user says a removed behavior returned,
  "thought we got rid of this," or "thrash," inspect cross-harness
  conversation history plus git/task history before editing, bind the
  strongest standing constraint to a guarded behavior, and invalidate
  rather than reconstruct a delegated task whose premise conflicts with it.
- **Error, log, and exit text is for humans.** Decide retry, cap, or status
  from the recorded state that drives it: a status, a phase, a
  launch-completed timestamp, a typed failure class, a gate's state file. A
  substring check on an error string is regex by another name; the same
  wording can come from two causes, and a reworded message changes the
  decision while the state stays put. Extending an existing text-match table
  is not precedent — replace it with the state. The same holds for two more
  kinds of text:
  - **Tool and agent output.** CLI stdout, PR and issue comments, CI logs, and
    model replies are written for people. Decide from the structured field or
    JSON output when one exists — `--output json`, an API field, an exit code,
    a typed status — never by matching the human-readable text.
  - **Plan and task prose.** Meaning that drives behavior comes from typed
    plan and task fields, not regex over descriptions or prompts.

  This is SKILL.md's typed-data-over-prose rule applied to text written for
  people. Dave Cheney,
  [Don't just check errors, handle them gracefully](https://dave.cheney.net/2016/04/27/dont-just-check-errors-handle-them-gracefully)
  (2016): never inspect the output of the `Error` method, which "exists for
  humans, not code". Alexis King,
  [Parse, don't validate](https://lexi-lambda.github.io/blog/2019/11/05/parse-don-t-validate/)
  (2019): turn input into a precise type once, at the boundary, and act on
  that type rather than re-checking the raw input.
- **A blocked target is a stop, not a licence to substitute.** When the named
  instrument, dataset, environment, date, or runtime cannot be reached — a
  lookup returns nothing, a vendor errors, a credential is missing, a runtime
  is busy — say so in that turn and stop. Do not proceed on the nearest
  reachable proxy. A substitution is a proposal the user accepts, never a
  fallback taken silently; a number produced on a proxy carries the proxy's
  name in the same message as the number. Before reaching for a third vendor
  or workaround, read `.env.example` and ask which paid source the user
  already has.
- **Re-resolve a target's live identity immediately before the action
  that mutates it; an earlier listing is not standing authorization to
  act on what it named.** A device table, session list, file index, or
  other resource inventory enumerated during investigation can be stale
  by the time a mutation actually runs: the same name, ID, or position
  can now point at a different live thing, or the original thing can
  have moved or been replaced. This differs from the blocked-target rule
  above — that one covers a target that cannot be reached at all; this
  one covers a target that can be reached but is no longer the one the
  earlier listing described. Confirm identity again from a live lookup
  immediately before mutating, not from the cache that first named it.
  No known prior art.
- **Repro evidence that genuinely can't be gathered is a stop, not
  licence to fix on hypothesis.** CLAUDE.md's Named constraints already
  requires a failing case captured before the change and a passing one
  after; the gap this closes is what happens when the failing case
  can't be captured at all — the environment, data, or access needed to
  trigger it is unavailable. That is a blocker to name and stop on, the
  same as a blocked target above, not a reason to write the fix against
  a guess and call it done once it merely stops looking wrong. A fix
  shipped without a captured failing case has nothing that proves it
  addressed the actual defect, only that the code changed. No known
  prior art.
- **A hook or classifier block is a stop, not a puzzle.** Do not reword a
  subagent prompt after `agent-routing-guard` refused it. Do not end a gated
  turn with a couldn't-verify tag instead of running the check the gate asked
  for. Do not reissue a denied command through a different tool, flag, or
  invocation; the classifier-denial rule in `corpus/CLAUDE.learned.md`
  already binds this shape. Do not open a change that makes a hook complain
  less. Do not relabel or relocate wording so that the region a checker
  inspects no longer contains it; the words stay where the check looks, or the
  check is raised with the user. Do what the block asks, and if the block is
  wrong, read the hook's source and raise it with the user with that evidence.
- **An answer given through a tool binds exactly as hard as a typed one.**
  A free-text reply to a multiple-choice question means every option offered
  was wrong. Restate it as a binding parameter in the plan before any work
  starts, and re-read it before each phase.
