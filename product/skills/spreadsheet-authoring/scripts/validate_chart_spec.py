#!/usr/bin/env python3
"""Validate the semantic contract for user-facing spreadsheet charts."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


GENERIC_LABELS = {"", "value", "values", "series", "data"}


def validate_chart_spec(spec: dict[str, Any]) -> list[str]:
    """Return errors for a chart spec that cannot explain its visual encodings."""
    errors: list[str] = []
    if spec.get("legendPosition") in (None, "NO_LEGEND"):
        errors.append("native in-graph legend is required")
    if int(spec.get("headerCount", 0)) < 1:
        errors.append("chart source must declare at least one header row")
    if spec.get("externalKey", False):
        errors.append("sheet-side key cannot substitute for the native legend")

    series = spec.get("series", [])
    if not series:
        errors.append("chart must contain at least one plotted series")
    labels = []
    for index, item in enumerate(series, start=1):
        label = str(item.get("header", "")).strip()
        if label.lower() in GENERIC_LABELS:
            errors.append(f"series {index}: semantic source header is required")
        labels.append(label.lower())
    if len(labels) != len(set(labels)):
        errors.append("series source headers must identify distinct visual encodings")
    return errors


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} SPEC.json", file=sys.stderr)
        return 2
    with Path(argv[1]).open(encoding="utf-8") as handle:
        errors = validate_chart_spec(json.load(handle))
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("ok: native semantic chart legend")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
