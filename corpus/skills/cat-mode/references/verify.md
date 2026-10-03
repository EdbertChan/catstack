# Verify: reporting, parity, and retraction

cat-mode's SKILL.md carries the evidence gate. These are the rules for what
happens to a number once it exists.

When a report and a repo/tool are requested together, the repo (or its
README) is the artifact-of-record — don't also publish a disconnected
write-up. A real number produced mid-session goes back into that one
place immediately, not left in chat until asked again.

- **Two of my own code paths disagreeing is my bug until proven otherwise.**
  When an internal inconsistency appears in a domain the user knows and the
  agent does not, name it as a suspected defect and ask. Do not invent a
  domain-level distinction that reconciles it — an explanation produced to
  rescue a failing comparison is an ad hoc hypothesis, not a finding.
- **Never satisfy a failing comparison with a second implementation.** If a
  parity, golden, or reference test fails, fix the path under test or drop the
  test's claim. A parallel helper, a fitted offset, or a separate code path
  that reproduces the reference turns the suite green and leaves every
  downstream number wrong. One exported function per behaviour; a test that
  does not call the entry point production calls proves nothing.
- **A stated caveat does not invalidate a number — only a gate does.** When a
  result is hedged as depending on an unvalidated step, stop emitting results
  that depend on that step until it has a passing check. Hedged numbers get
  spent, forwarded, and committed exactly like unhedged ones.
- **Retractions cover the conversation, not just the artifacts.** When a
  pipeline is voided, enumerate the numbers already said in chat as well as
  the ones in files and PRs. The user's belief came from the message.
- **An admission lists every live instance of the mistake.** When admitting
  a mistake, search for every place it still lives and list each one: the
  instance the user pointed at, other copies in files, PRs, and chat, and
  work the agent itself launched that carries the same mistake (running
  subagents, open PRs, queued workflows, scheduled jobs). Fixing only the
  named instance leaves the others running under a belief the admission
  already retracted. This extends [[principle-flag-your-own-corrections]]
  from saying the mistake out loud to saying where all of it is. Prior art:
  the "extent of condition" review in US NRC Inspection Procedure 95001
  (issue date 10/21/2020), which requires assessing "the degree that the
  actual condition ... may exist in other plant equipment, processes, or
  human performance", https://www.nrc.gov/docs/ML1917/ML19179A011.pdf.
- **A claim about the repo's own history is a query, not a recollection.**
  How long something was broken, how many passes found it, who wrote it,
  whether it ever ran — each is one `git log` and none is answerable from
  memory or from a file's mtime. State the command's output beside the claim,
  or tag it `{{CAT-UNVERIFIED: <claim> -- cannot verify: <reason>}}`. These are the cheapest facts available and
  the easiest to be confidently wrong about, which is why they reach PR bodies.

## Confirming a write, and keeping its output

- **The report of a write is not the write's effect.** A command that exits 0,
  a PR that reads `MERGED`, a label call that returns 200, an edit that says it
  applied — each is an acknowledgement from the layer that performed the
  action, not evidence of the state it was meant to produce. A batch of label
  calls can report applied with none applied; a PR can report merged with its
  commits absent from the trunk; a body can report edited and be unchanged.
  Verify by reading the changed thing back through a different path than the
  one that changed it: list the labels, look for the commit on the trunk,
  re-fetch the body, read the run that was supposedly triggered. This
  instantiates the end-to-end argument — Saltzer, Reed & Clark,
  [End-to-End Arguments in System Design](https://web.mit.edu/Saltzer/www/publications/endtoend/endtoend.pdf),
  ACM TOCS 2(4) 1984 — a check by an intermediate layer does not establish the
  property, so the endpoint that cares has to do it.
- **Never discard a mutating command's output.** Redirecting a write to
  `/dev/null` throws away the exit code and the diagnosis together, and a
  failing write usually prints exactly why it failed. Silencing output is for
  a read whose result is genuinely unused; a command that changes state never
  qualifies, however noisy it is. Fail-fast — Jim Shore,
  [Fail Fast](https://martinfowler.com/ieeeSoftware/failFast.pdf), IEEE
  Software 21(5) 2004 — and [[principle-explicit-errors]].
- **A teardown-only traceback is a flake: rerun once before diagnosing.** The
  signature is a test that "fails" while its own assertion passed — the failing
  frame sits in cleanup or fixture teardown and the rest of the suite is green.
  Rerun once first and investigate only if it reproduces — the one exception to
  SKILL.md's repro-before-retry rule, which otherwise counts a rerun as a fix. A frame inside the
  test body, or a failed assertion anywhere, is a real failure and this does
  not apply. Established concept: the flaky test; the teardown-frame signature
  itself has no known prior art.

## Original session on the product path

When repro+fixing a miss — a hook that failed to fire, a classifier that
let something through — replay the original error and session through the
product path before claiming fixed. Hand-built detector or unit payloads,
and nearby synthetic shapes, are not the original session. Evidence must
include the session or rollout (or a session fixture extracted from it)
exercised on the harness entrypoint that missed (for example a PreToolUse
entrypoint), not only the shared detect function. A green unit suite on
hand-built inputs is proof of those inputs, not of the miss. Extends
[[principle-prove-it]] and Named constraints.

## Unhedged causal claims about live system behavior

Unhedged root-cause or fix claims about live system behavior need
instrument-level proof in the same message, or a
`{{CAT-UNVERIFIED: <claim> -- cannot verify: <reason>}}` tag naming the
blocker. The gate is the claim type ("this is why it's slow," "this is the
bug"), not a hedge word.
Log-reading and code-reading aren't enough: attach with `strace`/a debugger, or
query live state (raw SQLite `PRAGMA`). Take a second sample before calling a
hang. Invoking `/prove-it` once does not arm it for later claims — each new
causal claim needs its own same-message evidence. Any hedge — "I think,"
"probably," a retired bare `UNVERIFIED:` — auto-runs prove-it in the same turn; a hedge is a
trigger to verify, never a place to stop.

## Visual Proof authenticity

Personal standing rules on top of [[visual-proof]] and [[principle-prove-it]].
These extend those skills; they harden authenticity when a near-neighbor
capture would otherwise stand in for the claimed surface.

- **The Visual Proof surface must match the Review Claim surface.** The claim
  names which product surface must be proved. Capture that surface's pixels —
  not a different product, not an upstream provider login, not an adjacent
  step that "looks related." A Slack-thread claim needs Slack-thread pixels; a Claude or OpenAI login page is not Slack UI proof.
- **Declare Expected surface and Expected predicates before capture.** Before
  any screenshot or frame grab, write (1) the Expected surface and (2) the
  Expected predicates: what must be visible, and what must not appear. Capture
  only after that list exists. Then `Manually inspected:` walks claim↔pixels
  against that list by reading the image (or extracted frames). A bare
  `Manually inspected:` marker with no predicate check is not a check.
- **Never submit synthesized UI as Visual Proof** unless the user explicitly
  asked for a mockup. Generated text slides (e.g. ffmpeg lavfi/drawtext), HTML mock surfaces,
  reconstructed controls, and redrawn UI prove only that the generator ran —
  not that the claimed surface showed the claimed state.

## Visual Proof case coverage

Personal standing rules on top of [[visual-proof]] and [[principle-prove-it]].
When a Review Claim or feature names multiple major behavioral cases —
disjuncts joined by OR — Visual Proof is incomplete until every named case
has its own UI proof media, or an explicit waiver that names the skipped
case.

- **One capture covers one case.** Pixels that prove one behavioral case
  (e.g. a usage-limit Slack thread) do not prove a different case the claim
  also covers (e.g. authentication-needed). Treat each major case as its
  own done-gate.
- **Declare Expected cases and Expected predicates before capture.** List
  every major case the claim covers, and for each case what must be visible
  and what must not appear. Capture only after that list exists. Then
  inspect claim↔pixels per case against that list.
- **An incomplete set is not done.** Shipping with proof for a subset of
  the claim's major cases, without a waiver naming each missing case, is
  an unfinished Visual Proof — not a partial success.

## Publishing analytics

Standing defaults when publishing hook/skill analytics — identity fields,
backfills, dashboards, and charts. Prefer fixing emit and coverage over
chart workarounds.

- **A blank or synthetic model on an analytics event is an emit bug.** Treat
  a missing or placeholder model as a write/backfill defect to fix at the
  source. Do not work around it by filtering the blank series out of a
  chart, swapping the breakdown to another dimension, or calling the blank
  "noise." The model field is an invariant of the event, not a display
  preference. [[principle-assert-invariants-not-last-bug]],
  [[principle-explicit-errors]].
- **"Full backfill" means every emitter of the metric.** A backfill that
  covers only the first harness that was easy is incomplete. Include every
  harness (or other emitter) that writes the metric before calling the
  backfill done. Same class as Harness-agnostic product defaults in
  SKILL.md.
- **Do not trust a metrics dashboard until install+probe shows the new
  identity fields on a live event.** Shipping a chart or notebook update is
  not proof the new fields land. Install the emitting path, probe a live
  event, and read the identity fields back before treating the dashboard as
  current. Extends "the report of a write is not the write's effect" and
  [[principle-prove-it]].
- **Keep a locked product question narrow.** When the ask is already locked
  (for example one chart per model), do not expand visualization scope —
  extra breakdowns, alternate filters, or adjacent charts — without an
  explicit new ask. Follow `narrow-the-scope`.
