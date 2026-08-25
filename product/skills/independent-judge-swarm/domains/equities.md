# Domain: equities

Triggers and consumer bindings for holdings / claim-research second opinions.
Do not restate the generic judge sequence in `SKILL.md`.

Catstack does **not** ship consumer grade/export scripts. Command paths come
only from a bindings file in the consumer workspace.

## Triggers

- `/holdings-sheet-swarm-grade <ticker>`
- Sheet URL + parent ticker
- Claim-research / sandbox report second opinion
- Words: holdings, Sheets export, research report, equities

## Consumer bindings

Look up this file under the consumer cwd (not shipped by catstack):

```text
.cursor/judge-swarm-bindings.json
```

Resolve commands with:

```bash
python3 ~/.cursor/skills/independent-judge-swarm/scripts/resolve_equities_bindings.py \
  --cwd "$PWD" \
  --ticker <TICKER> \
  --sheet-url '<URL>' \
  [--produce] \
  --json
```

If the bindings file or a path it names is missing, print the error and stop.
Never invent a CLI.

Fixture shape used by this skill’s tests (paths exist only under the test
cwd): `references/fixture_bindings.json`.

**After resolve succeeds:**

1. Uppercase / normalize the ticker per consumer rules.
2. Prefer local evidence files the consumer bindings describe over UI-only
   review.
3. Run resolved `produce` (if requested) then `grade` from the helper output.
4. Parent-specific mechanical anchors stay in the consumer’s own schema —
   not in this portable file.

**When bindings have no `grade` command:** produce shared board fields from
the report the user named; do not invent a grade CLI.

## Parent scope (assert)

- Always scope grades to the resolved parent.
- Do not reuse another parent’s numeric anchors.

## Auth

- Codex: `codex login`
- Fable: `claude login` with Fable access; unset stale `ANTHROPIC_API_KEY`
  if Claude returns 401

## Do not

- Self-grade the artifact the same agent just built
- Commit `.env` / OAuth tokens
- Hardcode consumer script paths into this skill
- Invent missing evidence
