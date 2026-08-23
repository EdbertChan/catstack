---
name: show-me-your-work
description: >
  Keep a reviewable decision trail for long-running or unattended work: a TSV
  log with one row per decision (what, why, evidence, result). Local by default;
  commit it when a reviewer needs the trail. Use for /show-me-your-work,
  overnight, babysit, autonomous, or multi-phase runs, or work a human reviews
  after stepping away. Not for a short same-turn fix — that's the evidence
  rules / prove-it gate.
---

# Show me your work

Adapted from pstack's `show-me-your-work` (MIT, Lauren Tan). Same trail
format. Cursor-only transcript globbing and poteto-mode routing dropped so
this works in Claude Code, Cursor, and Codex.

For work a human reviews after the fact, a decision trail lets them see what
was decided, why, and on what evidence, without rereading the whole
transcript. Keep one canonical log so the trail is consistent and a future
agent can find it.

This is not prove-it. Prove-it (CLAUDE.md evidence rules) is a same-turn
gate: don't claim "works" unless you checked it in this message. This skill
is a leftover table so someone can review after they left.

## The format

A single TSV file, one row per decision. TSV because GitHub renders it as a
sortable table, `column -s$'\t' -t` and spreadsheets read it, and a row
appends with one command. Cells stay single-line. Evidence is a pointer, not
prose.

Copy `references/decision-log-template.tsv` (the header row) to start a
clean log. Columns:

- **ts.** ISO8601 timestamp. The timeline axis.
- **phase.** The phase or workstream.
- **decision.** What was chosen or done, one line.
- **why.** The reason in plain words.
- **evidence.** A link or path that proves it: commit SHA, PR number,
  `file:line`, or an artifact, trace, or screenshot path. Never a paragraph.
- **result.** The outcome: `tests green`, `reverted`, `pixel-diff 0`,
  `INCONCLUSIVE`, `open`.

An example, plain-spoken so a reviewer reads it at a glance. Illustration
only; don't copy these rows into a real log.

```
ts	phase	decision	why	evidence	result
2026-05-24T09:02:00Z	frame	counted the work first, about 100 components	wanted the size before a long run	commit 3a9f1c2	found 5 things to sort out
2026-05-24T09:40:00Z	harness	took screenshots of the old version before changing anything	so we can compare old against new	scripts/snapshot.sh, baseline/	saved 120 reference screenshots
2026-05-24T11:15:00Z	widget	moved the widget styles over without changing how it looks	keep the change small	commit 7c21e0a, pixel-diff 0	looks identical, tests pass
2026-05-24T12:30:00Z	widget	threw out a helper's work because its screenshots were blank	checked the real files instead of its summary	worktree reset	reverted
```

## Logging a row

Write each entry the way you'd tell a teammate what you did. Plain words,
concrete actions.

Use the helper so rows stay well-formed:

```sh
scripts/log.sh <logfile> <phase> <decision> <why> <evidence> <result>
```

From a catstack install the helper is
`~/.cursor/skills/show-me-your-work/scripts/log.sh` (same tree under
`~/.claude/skills` or `~/.codex/skills`). It stamps `ts`, writes the header
on first use, strips stray tabs/newlines, and prefixes any cell starting
with `=`, `+`, `-`, or `@` with a single quote so a spreadsheet doesn't
treat it as a formula.

Log decision points and checkpoints, not every action: a fork chosen, a
unit completed with its verification result, a pivot or revert, a blocker,
a gate fixed. For loop runs, one row per iteration. Skip the trivial.

## Where it lives

By default the log is a working artifact, not committed. Keep it at
`decisions.tsv` in the work dir, or `.audit/<task-slug>.tsv` when several
efforts run at once, and leave it out of git. Most work doesn't need a
committed trail; the local log still keeps the run honest and can be
discarded after.

Commit it only when the work is ambitious enough that a reviewer needs the
trail to trust the result: a large port, a multi-week migration, anything
where confidence has to be shown rather than assumed. A committed log
renders as a table in the PR.

## Rules

- One row is one decision or checkpoint. If it doesn't fit on one line, the
  decision isn't crisp yet.
- Append-only. A wrong call gets a new row that supersedes it. Never edit
  or delete history.
- Prefer evidence produced by committed scripts over hand-made one-offs, so
  a reviewer can re-run it (`principle-encode-lessons-in-structure`).

## Audit the log against the transcript

At the end of the run, before handing back, check the log told the truth.
Read this run's transcript from the path the harness already named — don't
glob other projects' chats:

- Cursor: `~/.cursor/projects/<project>/agent-transcripts/<uuid>/<uuid>.jsonl`
  (the system prompt names it)
- Claude Code: `~/.claude/projects/<encoded-cwd>/*.jsonl`
- Codex: `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`

Walk the log against what actually happened:

- Every row maps to a real action. Cut invented or aspirational entries.
- Each row's evidence resolves and shows what the row claims.
- A fork, pivot, or abandoned approach that shaped the work but isn't
  logged is a gap. Add it.
- Drop padding. If nobody would audit a row, it doesn't earn its place.

Fix the log, not the story. If the work diverged from what a row claims,
the row is wrong.

## Cross-model review of the trail

Before handing back, spawn a subagent on a different model family from the
one that did the work. Self-review is not a substitute. The subagent reads
the audit trail and the run's transcript, then flags what the user should
pay attention to. Not a redo of the work — a scan for what's risky.

If the harness cannot spawn a different-family model, still list flags and
mark the Attention line `UNVERIFIED: same-model self-review`.

- Decisions logged with weak or absent evidence.
- Verification steps skipped or claimed without proof in the transcript.
- Choices that look risky in hindsight (premature, scope-creeping,
  papering over a symptom).
- Gaps the user would otherwise miss on a casual skim.

Every reply for a run that produced a trail ends with an "Attention"
section. Lead with the reviewer's model on its own line
(`reviewed by <model>`), then list each flag pointing to specific rows.
"No flags" is a valid value; the model name is not.

## Reviewing the trail

Read top to bottom, follow the evidence pointers, spot-check. GitHub
renders a committed TSV as a table; `column -s$'\t' -t decisions.tsv`
renders it in a terminal. A row whose evidence doesn't resolve, or whose
result is unverified, is the audit catching a gap.

## Composing this skill

Other skills route their audit trail here instead of inventing one.
Reference it by name and let it own the format; don't restate the columns.
`loop-generator` loops log one row per iteration here.
