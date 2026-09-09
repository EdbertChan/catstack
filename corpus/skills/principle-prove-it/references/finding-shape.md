# Shared finding shape

Every investigation product (`how`, `why`, `alternatives-considered`,
`spike-and-validate`) fans out to parallel subagents and merges their
returns. They share this shape so `principle-prove-it` can consume any of
them without a per-skill adapter.

This is **not** the judge board in `product/skills/independent-judge-swarm`.
That board grades a finished artifact (`verdict`, `score`,
`blocking_issues`). These skills return findings about work that has not
happened yet, so there is nothing to grade.

## Fields

| Field | Shape |
| --- | --- |
| `lens` | string — which angle this subagent owned |
| `claim` | string — one sentence, the thing found |
| `grounding` | `read-confirmed` \| `name-matched` \| `inferred` \| `invented` |
| `evidence` | `file:line` + ref, a command + its real output, or a URL |
| `ref` | which ref `evidence` was read at: working tree, `HEAD`, `origin/<base>`, installed bundle |
| `null_result` | string — what was searched and came back empty |

## Rules

- A subagent that found nothing still returns a row with `null_result` set.
  Silence is not the same as absence, and a skipped source is not a null —
  see the Evidence rules in `engine/CLAUDE.core.md`.
- `grounding: read-confirmed` means the subagent opened the actual
  reference and traced it. `name-matched` means the path or symbol name
  looked right. A working-tree read under a dirty path is `name-matched`.
- `grounding: inferred` and `grounding: invented` rows carry no authority
  on their own. They are hypotheses. Route an `invented` row that matters
  to `spike-and-validate` before it reaches a decision.
- The merge step reports disagreement rather than resolving it silently.

## Merge

1. Group rows by `claim`.
2. Two subagents reaching the same `read-confirmed` claim independently is
   the strongest signal available here. Check they were not handed the same
   anchor and prompt first — template-identical attempts converge on the
   same wrong answer exactly like independent ones agree.
3. Any `read-confirmed` row beats any number of `inferred` rows.
4. Report every `null_result` in the output. Do not drop it for brevity.

## Scope contract for the subagents

Every product that uses this shape fans out, so every one inherits
`principle-subagent-inherits-scope`. Two obligations, one per side.

**The parent states the boundary in the prompt.** Name the files or paths in
scope, the write authority (read-only, or its own worktree — never the live
checkout), and the single question. An unstated boundary is not inherited.

**The subagent returns a contradiction instead of acting on it.** When the
brief's premise is wrong — the named file does not exist, the symbol lives in
another package, two sources disagree — return an extra row:

| Field | Value for a contradiction |
| --- | --- |
| `lens` | the subagent's own lens |
| `claim` | what the brief assumed, and what is actually true |
| `grounding` | `read-confirmed`, or the row carries no weight |
| `evidence` | the command and its real output, or `file:line` + ref |
| `null_result` | which part of the assignment it could not complete |

Then finish what the brief validly covers and stop at the boundary. A
subagent that silently answers a better question has widened its scope; one
that silently conforms to a wrong brief has wasted the fan-out.

The merge step treats a `read-confirmed` contradiction as a re-scope signal,
not as one candidate among many. One subagent with a real command output
beats three that assumed the brief was right.
