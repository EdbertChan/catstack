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
