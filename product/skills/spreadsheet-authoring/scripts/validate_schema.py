#!/usr/bin/env python3
"""Validate the typed temporal columns used by spreadsheet authoring."""

from __future__ import annotations

import csv
import re
import sys
from datetime import date
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
    "Source URL",
    "Observation Type",
    "Derivation Method",
    "Derived From",
    "Notes",
}
QUALIFIER = re.compile(r"\b(avg|average|start|peak|end|low|high)\b", re.I)
KEY_FIELDS = ["Period Start", "Period End", "Observation Point", "Geography", "Scope", "Segment", "Entity", "Metric"]
DEFAULT_COVERAGE_FIELDS = [field for field in KEY_FIELDS if field != "Entity"]


def expected_period_starts(start: str, end: str, cadence: str = "quarterly") -> list[str]:
    """Return the typed period starts required by a selected coverage range."""
    if cadence != "quarterly":
        raise ValueError("unsupported cadence: " + cadence)
    first = date.fromisoformat(start)
    last = date.fromisoformat(end)
    if first > last:
        raise ValueError("period range start is after period range end")
    result: list[str] = []
    year, month = first.year, first.month
    while date(year, month, 1) <= last:
        result.append(date(year, month, 1).isoformat())
        month += 3
        if month > 12:
            year += (month - 1) // 12
            month = (month - 1) % 12 + 1
    return result


def validate_period_grid(rows: list[dict[str, str]], start: str, end: str, cadence: str = "quarterly") -> list[str]:
    """Require a raw or unresolved row for every period in the selected range."""
    try:
        expected = expected_period_starts(start, end, cadence)
    except ValueError as error:
        return ["invalid period range: " + str(error)]
    present = {row["Period Start"].strip() for row in rows}
    return ["period grid missing: " + period for period in expected if period not in present]


def validate_rows(
    rows: list[dict[str, str]],
    expected_entities: set[str] | None = None,
    coverage_fields: list[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    if not rows:
        return ["no observations"]
    missing = REQUIRED - set(rows[0])
    if missing:
        errors.append("missing columns: " + ", ".join(sorted(missing)))
        return errors
    keys: dict[tuple[str, ...], int] = {}
    coverage: dict[tuple[str, ...], set[str]] = {}
    for number, row in enumerate(rows, start=2):
        if QUALIFIER.search(row["Period Start"]) or QUALIFIER.search(row["Period End"]):
            errors.append(f"row {number}: qualifier embedded in period column")
        key = tuple(row[field].strip() for field in KEY_FIELDS)
        if key in keys:
            errors.append(f"row {number}: duplicate observation key; first seen at row {keys[key]}")
        else:
            keys[key] = number
        if not row["Source URL"].strip() and row["Value"].strip():
            errors.append(f"row {number}: numeric observation missing Source URL")
        if row["Observation Type"].strip().lower() == "derived estimate":
            method = row["Derivation Method"].strip().lower()
            if method not in {"midpoint", "linear interpolation"}:
                errors.append(f"row {number}: derived estimate has unsupported or missing derivation method")
            if not row["Derived From"].strip():
                errors.append(f"row {number}: derived estimate missing Derived From")
            if not re.search(r"\b(midpoint|average|formula|interpolat|\+|/\s*2)\b", row["Notes"], re.I):
                errors.append(f"row {number}: derived estimate missing derivation note")
        if expected_entities and row["Value"].strip() and row["Source URL"].strip() and row["Observation Type"].strip().lower() != "derived estimate":
            fields = coverage_fields or DEFAULT_COVERAGE_FIELDS
            group = tuple(row[field].strip() for field in fields)
            coverage.setdefault(group, set()).add(row["Entity"].strip())
    if expected_entities:
        for group, entities in coverage.items():
            missing = sorted(expected_entities - entities)
            if missing:
                label = ", ".join(f"{field}={value or '<blank>'}" for field, value in zip(coverage_fields or DEFAULT_COVERAGE_FIELDS, group))
                errors.append(f"coverage {label}: missing expected entities: {', '.join(missing)}")
    return errors


def validate_file(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return validate_rows(list(csv.DictReader(handle)))


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 4, 6, 8, 10, 12):
        print(f"usage: {argv[0]} FILE [--expected-entities A,B,C] [--coverage-fields A,B] [--period-start YYYY-MM-DD --period-end YYYY-MM-DD [--cadence quarterly]]", file=sys.stderr)
        return 2
    expected = None
    fields = None
    period_start = None
    period_end = None
    cadence = "quarterly"
    for index in range(2, len(argv), 2):
        if argv[index] == "--expected-entities":
            expected = {value.strip() for value in argv[index + 1].split(",") if value.strip()}
        elif argv[index] == "--coverage-fields":
            fields = [value.strip() for value in argv[index + 1].split(",") if value.strip()]
        elif argv[index] == "--period-start":
            period_start = argv[index + 1]
        elif argv[index] == "--period-end":
            period_end = argv[index + 1]
        elif argv[index] == "--cadence":
            cadence = argv[index + 1]
        else:
            print(f"unknown option: {argv[index]}", file=sys.stderr)
            return 2
    with Path(argv[1]).open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
        errors = validate_rows(rows, expected, fields)
    if (period_start is None) != (period_end is None):
        errors.append("period range requires both --period-start and --period-end")
    elif period_start and period_end:
        errors.extend(validate_period_grid(rows, period_start, period_end, cadence))
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("SPREADSHEET_COVERAGE: PASS" if expected else "ok: typed temporal schema")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
