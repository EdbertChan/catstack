A parent fanned out three investigators over a retry bug. One comes back
saying the brief pointed at the wrong module — the retry logic is not in
`queue/worker.py` at all. It gives no command output and no `file:line`, just
the assertion. The parent is about to re-scope the whole investigation on
that one report.

This skill fires. The subagent's report is a claim about code, and the parent
is about to act on it as settled fact with nothing run this turn — exactly
the gate's target. The scope contract added to
`references/finding-shape.md` is what the reply needs: a contradiction row
carries `grounding: read-confirmed` and a real command output or a
`file:line` with its ref, because a contradiction without evidence is
disagreement the parent cannot act on.

Correct handling is to verify before re-scoping, or to prefix the re-scope
with `UNVERIFIED:` — not to treat one delegate's unevidenced assertion as
having moved the investigation.
