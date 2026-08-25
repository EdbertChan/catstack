#!/usr/bin/env python3
"""Resolve equities judge-swarm bindings from a *consumer* repo cwd.

Catstack does not ship grade/export scripts. This resolver looks up relative
paths that exist in the workspace (e.g. hidden_stock) and builds the same
argv the pre-generic holdings-sheet-swarm-grade skill used.

Usage:
  python3 resolve_equities_bindings.py --cwd /path/to/hidden_stock \\
    --ticker UBER --sheet-url 'https://...' [--produce]
  python3 resolve_equities_bindings.py --cwd /path/to/hidden_stock --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Relative paths a consumer repo may provide. Missing → fail closed.
EXPORT_REL = Path("scripts/export_equity_holdings_sheets.py")
GRADE_REL = Path("scripts/grade_holdings_sheet.py")
SCHEMA_REL = Path(
    ".cursor/skills/holdings-sheet-swarm-grade/grade_schema.json"
)

# Frozen argv shapes from the pre-generic holdings-sheet-swarm-grade skill.
LEGACY_EXPORT_FLAGS = ("--live", "--history", "--new-sheet")
LEGACY_GRADE_JUDGES = "fable,codex"


def resolve(
    cwd: Path,
    *,
    ticker: str,
    sheet_url: str | None = None,
    produce: bool = False,
) -> dict:
    """Return binding dict. On missing required scripts, ok=False and errors[]."""
    root = cwd.resolve()
    errors: list[str] = []
    export_path = root / EXPORT_REL
    grade_path = root / GRADE_REL
    schema_path = root / SCHEMA_REL

    if not grade_path.is_file():
        errors.append(f"missing consumer script: {GRADE_REL.as_posix()}")
    if produce and not export_path.is_file():
        errors.append(f"missing consumer script: {EXPORT_REL.as_posix()}")

    resolved = ticker.strip().upper()
    if not resolved:
        errors.append("ticker is required")

    commands: list[dict] = []
    if produce and export_path.is_file():
        commands.append(
            {
                "name": "export",
                "relative": EXPORT_REL.as_posix(),
                "path": str(export_path),
                "argv": [
                    "python",
                    EXPORT_REL.as_posix(),
                    "--ticker",
                    resolved,
                    *LEGACY_EXPORT_FLAGS,
                ],
            }
        )

    if grade_path.is_file() and resolved:
        grade_argv = [
            "python",
            GRADE_REL.as_posix(),
            "--ticker",
            resolved,
            "--judges",
            LEGACY_GRADE_JUDGES,
        ]
        if sheet_url:
            grade_argv.extend(["--sheet-url", sheet_url])
        commands.append(
            {
                "name": "grade",
                "relative": GRADE_REL.as_posix(),
                "path": str(grade_path),
                "argv": grade_argv,
            }
        )

    return {
        "ok": not errors,
        "cwd": str(root),
        "ticker": resolved or None,
        "produce": produce,
        "sheet_url": sheet_url,
        "export_exists": export_path.is_file(),
        "grade_exists": grade_path.is_file(),
        "schema_exists": schema_path.is_file(),
        "export_path": str(export_path) if export_path.is_file() else None,
        "grade_path": str(grade_path) if grade_path.is_file() else None,
        "schema_path": str(schema_path) if schema_path.is_file() else None,
        "commands": commands,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cwd", type=Path, default=Path.cwd())
    p.add_argument("--ticker", default="")
    p.add_argument("--sheet-url", default=None)
    p.add_argument("--produce", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    result = resolve(
        args.cwd,
        ticker=args.ticker,
        sheet_url=args.sheet_url,
        produce=args.produce,
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        if not result["ok"]:
            for err in result["errors"]:
                print(f"error: {err}", file=sys.stderr)
            return 1
        for cmd in result["commands"]:
            print(" ".join(cmd["argv"]))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
