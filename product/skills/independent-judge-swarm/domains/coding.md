# Domain: coding

Triggers and cwd bindings for software / PR / CI second opinions. Do not
restate the generic judge sequence in `SKILL.md`.

## Triggers

- `/grade` on a PR, CI board, or local test failure
- “second opinion on this diff”
- Author claims PASS without an independent check

## Filename lookups (cwd)

Prefer the first that exists:

1. `scripts/run_all_tests.sh` — mechanical suite
2. `pytest` / `tests/` — unit suite as mechanical precheck
3. `visual-proof` skill — UI-affecting changes; open the capture before
   claiming what it shows

If none exist, say so and still run Fable + Codex on the diff/packet the
user named.

## Board mapping

Map shared board fields to review language (see `split-scope`):

- `blocking_issues` ↔ failed review claim or broken safety invariant
- `root_cause_class` ↔ class of bug across files, not one line
- `avoid_next_time` ↔ CI gate, regression test, or hook to add

Do not invent ticker or holdings checks in this domain.

## Do not

- Treat the authoring agent’s “tests look green” as the only judge
- Skip `visual-proof` when the change is UI-affecting and a capture path
  exists
- Re-run thrash without a new board after claiming a fix
