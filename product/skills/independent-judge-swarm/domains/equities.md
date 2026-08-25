# Domain: equities

Triggers and **consumer-repo** bindings for holdings sheets and claim-research
reports. Catstack does **not** ship grade/export scripts. Do not restate the
generic judge sequence in `SKILL.md`.

## Triggers

- `/holdings-sheet-swarm-grade <ticker>`
- Sheet URL + parent ticker
- Claim-research / sandbox report second opinion
- Words: holdings, 13F, 13G, Sheets export, research report

## Consumer bindings (filename lookups)

Resolve commands with the skill helper (fail closed if missing):

```bash
python3 ~/.cursor/skills/independent-judge-swarm/scripts/resolve_equities_bindings.py \
  --cwd "$PWD" \
  --ticker <TICKER> \
  --sheet-url '<URL>' \
  [--produce] \
  --json
```

Relative paths the consumer may provide (same as the pre-generic
`holdings-sheet-swarm-grade` skill):

| Role | Relative path in consumer cwd |
| --- | --- |
| export (optional, `--produce`) | `scripts/export_equity_holdings_sheets.py` |
| grade (required) | `scripts/grade_holdings_sheet.py` |
| schema (optional) | `.cursor/skills/holdings-sheet-swarm-grade/grade_schema.json` |

Frozen argv shapes live in
`references/hidden_stock_legacy_contract.json`. When those files exist under
cwd (as in `hidden_stock`), the resolver MUST emit that same argv. When they
do not exist, print the missing path and stop — never invent a CLI.

**Holdings sheet steps (after resolve succeeds):**

1. Resolve parent ticker (uppercase; consumer may use `normalize_parent`).
2. Prefer local CSV under `exports/<TICKER>_*.csv` over the sheet UI.
3. Run resolved `export` then `grade` commands from the helper output.
4. Prefer the consumer `grade_schema.json` for parent-specific mechanical
   checks (Uber DIDIY/GRAB/AUR anchors stay there, not in this portable file).

**Claim research (no grade script):**

1. Prefer a sandbox/cache report path the user named.
2. If `scripts/grade_holdings_sheet.py` is missing, produce shared board
   fields from the report — do not invent a grade CLI.

## Parent scope (assert)

- Always scope grades to the resolved parent.
- BABA sheets MUST NOT use Uber DIDIY/GRAB/AUR anchors (and vice versa).

## Auth

- Codex: `codex login`
- Fable: `claude login` with Fable access; unset stale `ANTHROPIC_API_KEY`
  if Claude returns 401

## Do not

- Self-grade the sheet the same agent just exported
- Commit `.env` / OAuth tokens
- Treat script basenames in this file as files that ship inside catstack
- Invent OTC marks or share counts when `$` is null
