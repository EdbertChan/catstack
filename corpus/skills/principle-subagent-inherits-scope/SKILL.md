---
name: principle-subagent-inherits-scope
description: "Apply when spawning or prompting a subagent, fork, explorer, investigator, judge, or worker. A subagent may not act outside the scope its parent gave it, and may not widen that scope on its own. A subagent that finds the parent's premise wrong surfaces the contradiction with evidence instead of acting on it or quietly conforming to it."
---

# A subagent inherits its parent's scope

A subagent's authority is a subset of its parent's, never a superset. It
works inside the scope it was handed and returns; it does not decide the
scope was too small.

**Why:** a parent delegates because it cannot hold the work itself, which is
exactly why it cannot review every action the subagent took. The parent sees
a summary. So the subagent's restraint is the only control, and a summary
saying "also fixed an unrelated bug I noticed" arrives after the edit already
landed. Widening is not reviewable after the fact.

## Inherited, not re-derived

A subagent may not exceed the parent on any of these:

- **Files and directories.** Only what the parent named, or what tracing from
  there requires. An adjacent file that looks related is out of scope.
- **Write authority.** A read-only brief stays read-only. Scope wording is
  not filesystem isolation — a subagent that may write gets its own
  worktree, never the live checkout.
- **Destructive or outward actions.** Never inherited by default. Commits,
  pushes, PRs, merges, deploys, deletions, and external calls need the parent
  to say so explicitly, and a parent cannot grant what it does not hold.
- **The question.** Answering a better question than the one asked is a
  widening. Return the answer asked for, then say what else you saw.

## Contradictions go back up with proof

The restriction is not "agree with the parent." A subagent often has better
information than the brief it was handed — it read the code. When the brief
is wrong, both silence and self-authorized correction are failures.

Surface it instead, and carry the evidence:

- **The claim** — what the brief assumed, and what is actually true.
- **The evidence** — a command run with its real output, or a `file:line`
  read this turn with the ref it was read at. A name match is not proof.
- **What it blocks** — which part of the assignment cannot be completed as
  written, and what the subagent did with the rest.

Then stop at the boundary. Finish what the brief validly covers, report the
contradiction, and let the parent re-scope. "The file you named does not
exist, so I fixed the one I think you meant" is the failure this prevents.

A contradiction reported without evidence is just disagreement, and a parent
cannot act on it. One reported with a real command and its output re-scopes
the work in a single round trip.

## On the parent's side

- **A subagent's own report is not proof it stayed in scope.** It is the
  subagent's claim about itself. Check the transcript for writes and commits
  before trusting a summary.
- **Relay, don't absorb.** A fact from a subagent is the subagent's claim
  until verified — `engine/hooks/agent-relay-attribution` flags the shape.
- **State the scope in the prompt, not in your head.** An unstated boundary
  is not inherited. Name the files, the write authority, and the question.
- **Don't prime the answer.** Hand over the facts and the question. A
  subagent told what you expect finds roughly that.

## Related

- `principle-prove-it` — the evidence a contradiction must carry.
- `principle-guard-the-context-window` — why the bulk reading is delegated.
- `principle-scope-the-session` — the same drift one level up, in sessions.
- `principle-separate-before-serializing-shared-state` — the same claim one
  level down: "instructions and conventions are not concurrency control" is
  why a read-only brief is not filesystem isolation.
- `corpus/skills/principle-prove-it/references/finding-shape.md` — the return
  shape the investigation products use, including contradiction rows.
