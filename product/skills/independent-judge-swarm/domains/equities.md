# Domain: equities

Triggers and cwd bindings for holdings sheets and claim-research reports.
Do not restate the generic judge sequence in `SKILL.md`.

## Triggers

- `/holdings-sheet-swarm-grade <ticker>`
- Sheet URL + parent ticker
- Claim-research / sandbox report second opinion
- Words: holdings, 13F, 13G, Sheets export, research report

## Filename lookups (cwd)

**Holdings sheet (hidden_stock-style):**

1. Resolve parent via `normalize_parent` if that helper exists in the
   package (aliases: tencent→TCEHY, alibaba→BABA, …).
2. Prefer local CSV under `exports/<TICKER>_*.csv` over the sheet UI.
3. If `--produce` / refresh requested and
   `scripts/export_equity_holdings_sheets.py` exists:

```bash
set -a && source .env && set +a
python scripts/export_equity_holdings_sheets.py \
  --ticker <RESOLVED> --live --history --new-sheet
```

4. If `scripts/grade_holdings_sheet.py` exists:

```bash
python scripts/grade_holdings_sheet.py \
  --ticker <RESOLVED> \
  --sheet-url '<URL>' \
  --judges fable,codex
```

5. If the grade script is missing, say so and stop — do not invent a CLI.

**Claim research (fraud_repo-style):**

1. Prefer a sandbox or cache-aware report path the user named (or printed
   by a local `run_sandbox.sh` / `run_company.sh` if present).
2. There may be no grade script yet — produce the shared board fields from
   the report + lineage checks; do not invent a grade CLI.

## Parent scope (assert)

- Always scope grades to the resolved parent.
- BABA sheets/CSVs/grades MUST NOT use Uber DIDIY/GRAB/AUR anchors (and
  vice versa). Parent-specific numeric anchors live in the repo’s
  `grade_schema.json` / mechanical precheck, not in the portable skill.

## Auth

- Codex: `codex login`
- Fable: `claude login` with Fable access; unset stale `ANTHROPIC_API_KEY`
  if Claude returns 401

## Do not

- Self-grade the sheet the same agent just exported
- Commit `.env` / OAuth tokens
- Mix parent-specific checks across tickers
- Invent OTC marks or share counts when `$` is null (mechanical must catch)
