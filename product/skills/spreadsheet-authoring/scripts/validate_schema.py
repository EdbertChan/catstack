#!/usr/bin/env python3
"""Validate the typed temporal columns used by spreadsheet authoring."""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path


REQUIRED = {
    "Original Period Label",
    "Period Start",
    "Period End",
    "Observation Point",
    "Geography",
    "Scope",
    "Segment",
    "Entity",
    "Metric",
    "Value",
}
QUALIFIER = re.compile(r"\b(avg|average|start|peak|end|low|high)\b", re.I)
KEY_FIELDS = ["Period Start", "Period End", "Observation Point", "Geography", "Scope", "Segment", "Entity", "Metric"]


def validate_rows(rows: list[dict[str, str]]) -> list[str]:
    errors: list[str] = []
    if not rows:
        return ["no observations"]
    missing = REQUIRED - set(rows[0])
    if missing:
        errors.append("missing columns: " + ", ".join(sorted(missing)))
        return errors
    keys: dict[tuple[str, ...], int] = {}
    for number, row in enumerate(rows, start=2):
        if QUALIFIER.search(row["Period Start"]) or QUALIFIER.search(row["Period End"]):
            errors.append(f"row {number}: qualifier embedded in period column")
        key = tuple(row[field].strip() for field in KEY_FIELDS)
        if key in keys:
            errors.append(f"row {number}: duplicate observation key; first seen at row {keys[key]}")
        else:
            keys[key] = number
    return errors


def validate_file(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return validate_rows(list(csv.DictReader(handle)))


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} FILE", file=sys.stderr)
        return 2
    errors = validate_file(Path(argv[1]))
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("ok: typed temporal schema")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
