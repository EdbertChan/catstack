from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wrap_installed

FAILURE_OUTCOMES = {"crashed", "timed_out", "caught_error"}
OUTCOMES = ("spoke", "silent", "blocked", "crashed", "caught_error", "timed_out")


def metrics_path() -> Path:
    root = os.environ.get("CATSTACK_HOOK_METRICS_DIR")
    if root is None:
        root = os.path.expanduser("~/.cache/catstack-hook-metrics")
    return Path(root) / "runs.jsonl"


def parse_since(value: str) -> timedelta:
    if value.endswith("h"):
        return timedelta(hours=float(value[:-1]))
    if value.endswith("d"):
        return timedelta(days=float(value[:-1]))
    raise ValueError(f"unsupported --since value: {value}")


def parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def key(row: dict[str, Any]) -> tuple[str, str, str]:
    return str(row.get("harness") or ""), str(row.get("hook") or ""), str(row.get("script") or "")


def read_registered() -> tuple[set[tuple[str, str, str]], list[str]]:
    home = Path(os.path.expanduser("~"))
    registered: set[tuple[str, str, str]] = set()
    unchecked = []
    for _harness, relative in wrap_installed.CONFIGS:
        path = home / relative
        if not path.exists():
            continue
        try:
            with path.open(encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            unchecked.append(f"unchecked config: {path}: {exc}")
            continue
        hooks = data.get("hooks") if isinstance(data, dict) else None
        for entry in wrap_installed._iter_command_objects(hooks):
            identity = wrap_installed._catstack_identity(entry["command"])
            if identity is not None:
                harness, hook, script, _trailing = identity
                registered.add((harness, hook, script))
    return registered, unchecked


def read_rows(path: Path, threshold: datetime) -> tuple[list[dict[str, Any]] | None, int, str | None]:
    try:
        with path.open(encoding="utf-8") as handle:
            lines = handle.readlines()
    except FileNotFoundError:
        return None, 0, f"unchecked: no metrics log at {path}"
    except OSError as exc:
        return None, 0, f"unchecked: {path}: {exc}"
    rows = []
    malformed = 0
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if not isinstance(row, dict):
            malformed += 1
            continue
        ts = parse_ts(row.get("ts"))
        if ts is None:
            malformed += 1
            continue
        if ts >= threshold:
            rows.append(row)
    return rows, malformed, None


def p95(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return ordered[index]


def first_line(value: object) -> str:
    if not isinstance(value, str):
        return ""
    for line in value.splitlines():
        if line.strip():
            return line.strip()
    return ""


def summarize_one(key_value: tuple[str, str, str], rows: list[dict[str, Any]]) -> dict[str, Any]:
    harness, hook, script = key_value
    summary: dict[str, Any] = {
        "harness": harness,
        "hook": hook,
        "script": script,
        "runs": len(rows),
        "spoke": 0,
        "silent": 0,
        "blocked": 0,
        "crashed": 0,
        "caught_error": 0,
        "timed_out": 0,
        "p95_ms": None,
        "last_error": "",
        "no_record": not rows,
    }
    if not rows:
        return summary
    durations = []
    newest_failure: tuple[datetime, str] | None = None
    for row in rows:
        outcome = row.get("outcome")
        if outcome in OUTCOMES:
            summary[outcome] += 1
        duration = row.get("duration_ms")
        if isinstance(duration, int) and not isinstance(duration, bool):
            durations.append(duration)
        if outcome in FAILURE_OUTCOMES:
            line = first_line(row.get("stderr_tail"))
            ts = parse_ts(row.get("ts"))
            if line and ts is not None and (newest_failure is None or ts > newest_failure[0]):
                newest_failure = (ts, line)
    summary["p95_ms"] = p95(durations)
    if newest_failure is not None:
        summary["last_error"] = newest_failure[1]
    return summary


def build_report(registered: set[tuple[str, str, str]], rows: list[dict[str, Any]], malformed: int, config_warnings: list[str]) -> dict[str, Any]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(key(row), []).append(row)
    registered_rows = []
    for item in sorted(registered):
        registered_rows.append(summarize_one(item, grouped.pop(item, [])))
    unregistered = []
    for item in sorted(grouped):
        unregistered.append(summarize_one(item, grouped[item]))
    return {
        "window_rows": len(rows),
        "malformed_rows": malformed,
        "config_warnings": config_warnings,
        "registered": registered_rows,
        "unregistered": unregistered,
    }


def format_counts(row: dict[str, Any]) -> str:
    if row["no_record"]:
        return "no record"
    return (
        f"{row['runs']} {row['spoke']} {row['silent']} {row['blocked']} "
        f"{row['crashed']} {row['caught_error']} {row['timed_out']} "
        f"{row['p95_ms'] if row['p95_ms'] is not None else '-'} {row['last_error']}"
    ).rstrip()


def format_table(report: dict[str, Any]) -> str:
    lines = []
    for warning in report["config_warnings"]:
        lines.append(warning)
    if report["malformed_rows"]:
        lines.append(f"skipped {report['malformed_rows']} malformed row(s)")
    lines.append("harness hook/script runs spoke silent blocked crashed caught_error timed_out p95_ms last_error")
    for row in report["registered"]:
        lines.append(f"{row['harness']} {row['hook']}/{row['script']} {format_counts(row)}")
    if report["unregistered"]:
        lines.append("unregistered:")
        for row in report["unregistered"]:
            lines.append(f"{row['harness']} {row['hook']}/{row['script']} {format_counts(row)}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", default="7d")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        since = parse_since(args.since)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    path = metrics_path()
    rows, malformed, error = read_rows(path, datetime.now(timezone.utc) - since)
    if error is not None:
        print(error)
        return 2
    registered, warnings = read_registered()
    report = build_report(registered, rows or [], malformed, warnings)
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print(format_table(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
