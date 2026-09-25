#!/usr/bin/env python3
"""Fold an append-only JSONL state ledger to latest state per group.

Workers that scan a queue and append rows to a JSONL ledger produce raw
history, not answers. Consumers should read the folded digest — the latest
row per group — instead of re-parsing the whole log or re-querying the live
source. This is the generic fold behind the principle: point it at any
append-only JSONL ledger whose rows carry a timestamp-ish field.

Usage:
    fold_jsonl_state.py LEDGER.jsonl --by pr,kind,key
    fold_jsonl_state.py LEDGER.jsonl --by pr --json

Each group keeps the row with the greatest ordering field (`--order`,
default `epoch`; falls back to input line order when absent). Malformed
lines are skipped and counted on stderr. Output is one compact line per
group, sorted by group key; `--json` emits one JSON object per group.

Read-only by construction: parses the ledger and prints, nothing else.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("ledger", help="Path to the append-only JSONL ledger.")
    p.add_argument("--by", required=True, help="Comma-separated fields that identify one group (e.g. pr,kind,key).")
    p.add_argument("--order", default="epoch", help="Field that orders rows; greatest wins. Default: epoch. Falls back to line order when the field is missing.")
    p.add_argument("--json", action="store_true", help="Emit one JSON object per group instead of text lines.")
    return p.parse_args(argv)


def load_rows(path: Path) -> tuple[list[dict], int]:
    rows: list[dict] = []
    bad = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            bad += 1
            continue
        if isinstance(row, dict):
            rows.append(row)
        else:
            bad += 1
    return rows, bad


def fold(rows: list[dict], by: list[str], order: str) -> dict[tuple, dict]:
    """Latest row per group tuple; ties keep the later input row."""
    latest: dict[tuple, dict] = {}
    latest_rank: dict[tuple, tuple[float, int]] = {}
    for seq, row in enumerate(rows):
        key = tuple(row.get(f) for f in by)
        rank_val = row.get(order)
        try:
            rank_num = float(rank_val) if rank_val is not None else float("-inf")
        except (TypeError, ValueError):
            rank_num = float("-inf")
        rank = (rank_num, seq)
        if key not in latest or rank >= latest_rank[key]:
            latest[key] = row
            latest_rank[key] = rank
    return latest


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    path = Path(args.ledger).expanduser()
    if not path.exists():
        print(f"ledger not found: {path}", file=sys.stderr)
        return 1
    by = [f.strip() for f in args.by.split(",") if f.strip()]
    if not by:
        print("--by must name at least one field", file=sys.stderr)
        return 1
    rows, bad = load_rows(path)
    if bad:
        print(f"skipped {bad} malformed line(s)", file=sys.stderr)
    groups = fold(rows, by, args.order)
    for key in sorted(groups, key=lambda k: tuple(str(v) for v in k)):
        row = groups[key]
        if args.json:
            print(json.dumps(row, sort_keys=True))
        else:
            head = " ".join(f"{f}={row.get(f)}" for f in by)
            rest = " ".join(f"{k}={v}" for k, v in sorted(row.items()) if k not in by)
            print(f"{head}  {rest}".rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
