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
    "Source URL",
    "Observation Type",
    "Derivation Method",
    "Derived From",
    "Notes",
}
QUALIFIER = re.compile(r"\b(avg|average|start|peak|end|low|high)\b", re.I)
KEY_FIELDS = ["Period Start", "Period End", "Observation Point", "Geography", "Scope", "Segment", "Entity", "Metric"]
DEFAULT_COVERAGE_FIELDS = [field for field in KEY_FIELDS if field != "Entity"]


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
    if len(argv) not in (2, 4, 6):
        print(f"usage: {argv[0]} FILE [--expected-entities A,B,C] [--coverage-fields A,B]", file=sys.stderr)
        return 2
    expected = None
    fields = None
    for index in range(2, len(argv), 2):
        if argv[index] == "--expected-entities":
            expected = {value.strip() for value in argv[index + 1].split(",") if value.strip()}
        elif argv[index] == "--coverage-fields":
            fields = [value.strip() for value in argv[index + 1].split(",") if value.strip()]
        else:
            print(f"unknown option: {argv[index]}", file=sys.stderr)
            return 2
    with Path(argv[1]).open(newline="", encoding="utf-8") as handle:
        errors = validate_rows(list(csv.DictReader(handle)), expected, fields)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("SPREADSHEET_COVERAGE: PASS" if expected else "ok: typed temporal schema")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
