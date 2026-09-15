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
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "_sdk"))

import registry as hook_registry
import wrap_installed

FAILURE_OUTCOMES = {"crashed", "timed_out", "caught_error"}
OUTCOMES = ("spoke", "silent", "blocked", "crashed", "caught_error", "timed_out")
EVENT_ACTIONS = {"silent", "stopped", "warned", "unchecked", "crashed", "followup", "hit", "clean"}
CLOSED_OUTCOMES = {"acted", "ignored", "overridden"}
FIRE_ACTIONS = {"stopped", "warned", "hit"}


def metrics_root() -> Path:
    root = os.environ.get("CATSTACK_HOOK_METRICS_DIR")
    if root is None:
        root = os.path.expanduser("~/.cache/catstack-hook-metrics")
    return Path(root)


def metrics_path() -> Path:
    return metrics_root() / "runs.jsonl"


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


def read_rows(
    path: Path,
    threshold: datetime,
    missing_label: str = "metrics log",
) -> tuple[list[dict[str, Any]] | None, int, str | None]:
    try:
        with path.open(encoding="utf-8") as handle:
            lines = handle.readlines()
    except FileNotFoundError:
        return None, 0, f"unchecked: no {missing_label} at {path}"
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


def _fleet_event_paths(directory: Path, unchecked: list[str]) -> list[Path]:
    try:
        entries = sorted(directory.iterdir())
    except OSError as exc:
        unchecked.append(f"unchecked: {directory}: {exc}")
        return []

    paths: list[Path] = []
    for entry in entries:
        if entry.name.startswith("events-") and entry.name.endswith(".jsonl"):
            paths.append(entry)
            continue
        try:
            is_directory = entry.is_dir() and not entry.is_symlink()
        except OSError as exc:
            unchecked.append(f"unchecked: {entry}: {exc}")
            continue
        if is_directory:
            paths.extend(_fleet_event_paths(entry, unchecked))
    return paths


def event_paths(root: Path) -> tuple[list[Path], list[str]]:
    try:
        entries = sorted(root.iterdir())
    except FileNotFoundError:
        return [], [f"unchecked: no event logs at {root}"]
    except OSError as exc:
        return [], [f"unchecked: {root}: {exc}"]

    paths = [
        entry
        for entry in entries
        if entry.name.startswith("events-") and entry.name.endswith(".jsonl")
    ]
    unchecked: list[str] = []
    fleet = root / "fleet"
    if fleet in entries:
        try:
            is_directory = fleet.is_dir()
        except OSError as exc:
            unchecked.append(f"unchecked: {fleet}: {exc}")
        else:
            if is_directory:
                paths.extend(_fleet_event_paths(fleet, unchecked))
            else:
                unchecked.append(f"unchecked: {fleet}: expected a directory")
    if not paths and not unchecked:
        unchecked.append(f"unchecked: no event logs at {root} or {fleet}")
    return sorted(paths), unchecked


def valid_event_row(row: dict[str, Any]) -> bool:
    action = row.get("action")
    if not isinstance(row.get("hook"), str) or not row.get("hook"):
        return False
    if action not in EVENT_ACTIONS:
        return False
    if action == "followup" and row.get("outcome") not in CLOSED_OUTCOMES | {"unchecked"}:
        return False
    return True


def read_event_rows(root: Path, threshold: datetime) -> tuple[list[dict[str, Any]], int, list[str]]:
    paths, unchecked = event_paths(root)
    rows: list[dict[str, Any]] = []
    malformed = 0
    for path in paths:
        file_rows, file_malformed, error = read_rows(path, threshold, missing_label="event file")
        malformed += file_malformed
        if error is not None:
            unchecked.append(error)
            continue
        for row in file_rows or []:
            if valid_event_row(row):
                rows.append(row)
            else:
                malformed += 1
    return rows, malformed, unchecked


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


def _event_summary(hook: str, rule_id: str) -> dict[str, Any]:
    return {
        "hook": hook,
        "rule_id": rule_id,
        "mode": "unknown",
        "fires": 0,
        "stopped": 0,
        "warned": 0,
        "acted": 0,
        "ignored": 0,
        "overridden": 0,
        "unchecked": 0,
        "crashes": 0,
        "runs": 0,
        "p95_ms": None,
        "effective_ignore_rate": None,
        "suggestion": "review registry",
        "_durations": [],
        "_closures": [],
    }


def _event_rule_key(row: dict[str, Any]) -> tuple[str, str] | None:
    hook = str(row.get("hook") or "")
    rule_id = str(row.get("rule_id") or "")
    if not hook:
        return None
    if rule_id:
        return hook, rule_id
    if row.get("action") in {"crashed", "unchecked"}:
        return hook, "-"
    return None


def _suggestion(
    summary: dict[str, Any],
    record: hook_registry.HookRecord,
    thresholds: hook_registry.Thresholds,
) -> str:
    runs = summary["runs"]
    failure_rate = (summary["crashes"] + summary["unchecked"]) / runs if runs else 0.0
    closures = sorted(summary["_closures"], key=lambda item: item[0])
    if failure_rate > thresholds.review_min_unchecked_rate:
        return "review or turn off"
    if len(closures) < thresholds.min_closed_findings:
        return "not enough data"

    recent = closures[-thresholds.min_closed_findings :]
    recent_ignored = sum(outcome in {"ignored", "overridden"} for _ts, outcome in recent)
    recent_ignore_rate = recent_ignored / len(recent)
    effective_ignore_rate = summary["effective_ignore_rate"]
    if record.mode == "stop" and recent_ignore_rate > thresholds.demote_min_ignore_rate:
        return "stop to warn"
    if (
        record.mode == "warn"
        and effective_ignore_rate is not None
        and effective_ignore_rate > thresholds.review_min_ignore_rate
    ):
        return "review or turn off"
    if (
        record.mode == "warn"
        and effective_ignore_rate is not None
        and effective_ignore_rate <= thresholds.promote_max_ignore_rate
        and record.why_mode in {"attention", "outward"}
    ):
        return "warn to stop"
    return "no change"


def build_event_report(
    rows: list[dict[str, Any]],
    malformed: int,
    unchecked: list[str],
    hooks: dict[str, hook_registry.HookRecord],
    thresholds: hook_registry.Thresholds,
) -> dict[str, Any]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    closed_findings: set[tuple[str, str, str]] = set()
    for row in rows:
        key_value = _event_rule_key(row)
        if key_value is None:
            continue
        summary = grouped.setdefault(key_value, _event_summary(*key_value))
        action = row.get("action")
        if action == "followup":
            outcome = str(row.get("outcome"))
            finding_id = str(row.get("finding_id") or "")
            closure_key = (key_value[0], key_value[1], finding_id)
            if finding_id and closure_key in closed_findings:
                continue
            if finding_id:
                closed_findings.add(closure_key)
            if outcome in CLOSED_OUTCOMES:
                summary[outcome] += 1
                summary["_closures"].append((parse_ts(row.get("ts")), outcome))
            elif outcome == "unchecked":
                summary["unchecked"] += 1
            continue

        summary["runs"] += 1
        if action in FIRE_ACTIONS:
            summary["fires"] += 1
        if action == "stopped":
            summary["stopped"] += 1
        elif action == "warned":
            summary["warned"] += 1
        elif action == "unchecked":
            summary["unchecked"] += 1
        elif action == "crashed":
            summary["crashes"] += 1
        duration = row.get("duration_ms")
        if isinstance(duration, int) and not isinstance(duration, bool):
            summary["_durations"].append(duration)

    rules = []
    for key_value in sorted(grouped):
        summary = grouped[key_value]
        summary["p95_ms"] = p95(summary["_durations"])
        closed = summary["acted"] + summary["ignored"] + summary["overridden"]
        if closed:
            summary["effective_ignore_rate"] = (summary["ignored"] + summary["overridden"]) / closed
        record = hooks.get(summary["hook"])
        if record is not None:
            summary["mode"] = record.mode
            summary["suggestion"] = _suggestion(summary, record, thresholds)
        del summary["_durations"]
        del summary["_closures"]
        del summary["runs"]
        rules.append(summary)
    return {
        "window_rows": len(rows),
        "malformed_rows": malformed,
        "unchecked": unchecked,
        "rules": rules,
    }


def format_event_table(report: dict[str, Any]) -> str:
    lines = list(report["unchecked"])
    if report["malformed_rows"]:
        lines.append(f"skipped {report['malformed_rows']} malformed event row(s)")
    lines.append(
        "hook rule_id mode fires stopped warned acted ignored overridden unchecked crashes "
        "p95_ms effective_ignore_rate suggestion"
    )
    for row in report["rules"]:
        ignore_rate = row["effective_ignore_rate"]
        formatted_rate = "-" if ignore_rate is None else f"{ignore_rate:.1%}"
        lines.append(
            f"{row['hook']} {row['rule_id']} {row['mode']} {row['fires']} {row['stopped']} "
            f"{row['warned']} {row['acted']} {row['ignored']} {row['overridden']} "
            f"{row['unchecked']} {row['crashes']} "
            f"{row['p95_ms'] if row['p95_ms'] is not None else '-'} {formatted_rate} "
            f"{row['suggestion']}"
        )
    return "\n".join(lines) + "\n"


def run_events(args: argparse.Namespace, threshold: datetime) -> int:
    rows, malformed, unchecked = read_event_rows(metrics_root(), threshold)
    try:
        hooks, thresholds = hook_registry.load_registry()
    except hook_registry.RegistryError as exc:
        print(f"unchecked: {exc}")
        return 2
    report = build_event_report(rows, malformed, unchecked, hooks, thresholds)
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print(format_event_table(report), end="")
    return 2 if unchecked else 0


def run_legacy(args: argparse.Namespace, threshold: datetime) -> int:
    path = metrics_path()
    rows, malformed, error = read_rows(path, threshold)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", default="7d")
    parser.add_argument("--json", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--events", dest="report_mode", action="store_const", const="events")
    mode.add_argument("--runs", dest="report_mode", action="store_const", const="runs")
    parser.set_defaults(report_mode="events")
    args = parser.parse_args(argv)
    try:
        since = parse_since(args.since)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    threshold = datetime.now(timezone.utc) - since
    if args.report_mode == "runs":
        return run_legacy(args, threshold)
    return run_events(args, threshold)


if __name__ == "__main__":
    raise SystemExit(main())
