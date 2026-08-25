---
name: independent-judge-swarm
description: >-
  Grade an artifact with a mechanical precheck plus two independent judges
  (Fable + Codex). Building agent must not self-grade. Use for /grade,
  /holdings-sheet-swarm-grade, sheet/report second opinions, or when a
  PASS from the author alone is not enough. Domain files under domains/
  bind coding vs equities triggers and cwd scripts.
disable-model-invocation: true
---

# Independent judge swarm

Second opinions from judges that did **not** build the artifact. Mechanical
precheck first, then Fable + Codex in parallel. On FAIL, run
`thrash-reflect-automate` — do not re-prompt the user for that sequence.

## Domain selector

After reading this file, read **at most one** sibling `domains/<type>.md`:

1. User named the type (`coding`, `equities`, holdings, claim research).
2. Else cwd has `.cursor/judge-swarm-bindings.json`, or equities trigger
   words (holdings, Sheets, research report) → `equities`; Invoker /
   catstack / `package.json` without those → `coding`.
3. Else none. Do not read both in one turn.

## Invariants (assert)

- The building agent MUST NOT be the sole judge.
- Run a **mechanical precheck** before or beside LLM judges when a script
  exists; LLM PASS alone is not enough when invent/uniqueness can hide.
- Use **two independent judges** (Fable + Codex) in parallel when both are
  available. If one is missing auth, report that and still run the other.
- Prefer local evidence files over “looks fine in the UI.”
- If judges disagree on a blocking check, report BOTH and treat as
  `needs_work`.
- Do not paraphrase away a FAIL.
- On FAIL / NEEDS_WORK: invoke `thrash-reflect-automate` (reflect → fix the
  class → codify invariant → automate a catch → re-validate). Prefer
  `principle-assert-invariants-not-last-bug` for the class fix.

## Shared board fields

Every judge output MUST include at least:

| Field | Shape |
| --- | --- |
| `judge` | string |
| `verdict` | `pass` \| `fail` \| `needs_work` |
| `score` | integer 0–100 |
| `blocking_issues` | list of `{id, severity, evidence}` |
| `root_cause_class` | string (class of bug, not instance name) |
| `avoid_next_time` | string (mechanical catch to add) |

Domain files may require extra fields. Parent-specific or ticker-specific
checks belong in the domain file or the repo’s grade schema — not here.

## Generic workflow

1. Resolve the artifact under review (path, URL, or PR) from the user or
   the domain file.
2. If a mechanical grade/precheck script exists in cwd (see domain), run it.
3. Spawn Fable and Codex judges with the same packet; collect boards.
4. Merge: any blocking FAIL → overall FAIL; else disagreement →
   `needs_work`; else PASS.
5. Reply with verdicts, blocking issues, agreement/disagreement, and one
   recommended next fix.
6. On FAIL / NEEDS_WORK, run `thrash-reflect-automate` before declaring
   done.

## Do not

- Invent a CLI that is not present in the cwd.
- Put consumer script paths in this generic file. Equities bindings are
  loaded from the consumer’s `.cursor/judge-swarm-bindings.json` via
  `scripts/resolve_equities_bindings.py`.
- Self-grade and stop.
- Claim fixed without a new board after thrash.
