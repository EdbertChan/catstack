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
- **A claim about the repo's own history is a query, not a recollection.**
  How long something was broken, how many passes found it, who wrote it,
  whether it ever ran — each is one `git log` and none is answerable from
  memory or from a file's mtime. State the command's output beside the claim,
  or write `UNVERIFIED:` before it. These are the cheapest facts available and
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

## Unhedged causal claims about live system behavior

Unhedged root-cause or fix claims about live system behavior need
instrument-level proof in the same message, or `UNVERIFIED:`. The gate is the
claim type ("this is why it's slow," "this is the bug"), not a hedge word.
Log-reading and code-reading aren't enough: attach with `strace`/a debugger, or
query live state (raw SQLite `PRAGMA`). Take a second sample before calling a
hang. Invoking `/prove-it` once does not arm it for later claims — each new
causal claim needs its own same-message evidence. Any hedge — "I think,"
"probably," `UNVERIFIED:` — auto-runs prove-it in the same turn; a hedge is a
trigger to verify, never a place to stop.
