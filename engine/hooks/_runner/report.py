from __future__ import annotations

import argparse
import html
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wrap_installed

SDK_DIR = Path(__file__).resolve().parents[1] / "_sdk"
sys.path.insert(0, str(SDK_DIR))

import registry

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skill-usage-log"))

import detect as skill_detect

FAILURE_OUTCOMES = {"crashed", "timed_out", "caught_error"}
OUTCOMES = ("spoke", "silent", "blocked", "crashed", "caught_error", "timed_out")
DASHBOARD_WINDOW_SECONDS = 2.0


def metrics_path() -> Path:
    root = os.environ.get("CATSTACK_HOOK_METRICS_DIR")
    if root is None:
        root = os.path.expanduser("~/.cache/catstack-hook-metrics")
    return Path(root) / "runs.jsonl"


def metrics_dir() -> Path:
    root = os.environ.get("CATSTACK_HOOK_METRICS_DIR")
    if root is None:
        root = os.path.expanduser("~/.cache/catstack-hook-metrics")
    return Path(root)


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
    notify_path = home / wrap_installed.CODEX_CONFIG
    if notify_path.exists():
        try:
            _text, _match, argv = wrap_installed.read_notify(notify_path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            unchecked.append(f"unchecked config: {notify_path}: notify: {exc}")
            argv = None
        for identity in wrap_installed.notify_identities(argv or [], str(home)):
            hook, script = identity.split("/", 1)
            registered.add(("codex", hook, script))
    return registered, unchecked


def rotated_paths(path: Path) -> list[Path]:
    prefix = path.name + "."
    indexed = []
    for candidate in path.parent.glob(prefix + "*"):
        suffix = candidate.name[len(prefix) :]
        if suffix.isdigit():
            indexed.append((int(suffix), candidate))
    return [candidate for _index, candidate in sorted(indexed, reverse=True)]


def read_rows(path: Path, threshold: datetime) -> tuple[list[dict[str, Any]] | None, int, str | None]:
    try:
        older = rotated_paths(path)
    except OSError as exc:
        return None, 0, f"unchecked: {path.parent}: {exc}"
    lines = []
    for source in [*older, path]:
        try:
            with source.open(encoding="utf-8") as handle:
                lines.extend(handle.readlines())
        except FileNotFoundError:
            if source == path:
                return None, 0, f"unchecked: no metrics log at {path}"
            return None, 0, f"unchecked: {source} was rotated away while reading"
        except OSError as exc:
            return None, 0, f"unchecked: {source}: {exc}"
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


def _event_paths_in(directory: Path) -> tuple[list[Path], list[str]]:
    try:
        return sorted(directory.glob("events-*.jsonl")), []
    except OSError as exc:
        return [], [f"unchecked machine: {directory}: {exc}"]


def event_paths(root: Path) -> tuple[list[Path], list[str]]:
    paths, warnings = _event_paths_in(root)
    fleet = root / "fleet"
    if not fleet.exists():
        return paths, warnings
    if not fleet.is_dir():
        return paths, warnings + [f"unchecked machine: {fleet}: not a directory"]

    fleet_paths, fleet_warnings = _event_paths_in(fleet)
    paths.extend(fleet_paths)
    warnings.extend(fleet_warnings)
    try:
        children = sorted(fleet.iterdir())
    except OSError as exc:
        warnings.append(f"unchecked machine: {fleet}: {exc}")
        return paths, warnings
    for child in children:
        if child.name.startswith("events-") and child.suffix == ".jsonl":
            continue
        if not child.is_dir():
            continue
        child_paths, child_warnings = _event_paths_in(child)
        paths.extend(child_paths)
        warnings.extend(child_warnings)
        if not child_paths:
            warnings.append(f"unchecked machine: {child}: no readable event files")
    return sorted(set(paths)), warnings


def read_event_rows(root: Path, threshold: datetime) -> tuple[list[dict[str, Any]] | None, int, list[str]]:
    paths, warnings = event_paths(root)
    if not paths and not warnings:
        return None, 0, [f"unchecked: no event logs under {root}"]
    rows: list[dict[str, Any]] = []
    malformed = 0
    for path in paths:
        try:
            with path.open(encoding="utf-8") as handle:
                lines = handle.readlines()
        except FileNotFoundError as exc:
            warnings.append(f"unchecked file: {path}: {exc}")
            continue
        except OSError as exc:
            warnings.append(f"unchecked file: {path}: {exc}")
            continue
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
    return rows, malformed, warnings


def p95(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return ordered[index]


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * quantile) - 1)
    return round(ordered[index], 3)


def format_rate(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}"


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
        "blocked": sum(1 for row in rows if row.get("outcome") == "blocked"),
        "failures": sum(1 for row in rows if row.get("outcome") in FAILURE_OUTCOMES),
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
    lines.append(f"blocked {report['blocked']}")
    lines.append(f"failures {report['failures']}")
    return "\n".join(lines) + "\n"


def _read_dashboard_rows(path: Path, threshold: datetime) -> tuple[list[dict[str, Any]], int, list[str]]:
    rows, malformed, error = read_rows(path, threshold)
    if error is None:
        return rows or [], malformed, []
    if error.startswith("unchecked: no metrics log at "):
        return [], 0, []
    return [], malformed, [error]


def _read_dashboard_event_rows(root: Path, threshold: datetime) -> tuple[list[dict[str, Any]], int, list[str]]:
    rows, malformed, warnings = read_event_rows(root, threshold)
    if rows is None and warnings == [f"unchecked: no event logs under {root}"]:
        return [], 0, []
    return rows or [], malformed, warnings


def _duration_ms(row: dict[str, Any]) -> int:
    value = row.get("duration_ms")
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return 0


def _event_type(row: dict[str, Any]) -> str:
    return str(row.get("event") or "unknown")


def _row_end(row: dict[str, Any]) -> datetime | None:
    return parse_ts(row.get("ts"))


def _row_start(row: dict[str, Any]) -> datetime | None:
    end = _row_end(row)
    if end is None:
        return None
    return end - timedelta(milliseconds=_duration_ms(row))


def _event_group_summary(event_type: str, rows: list[dict[str, Any]], source: str) -> dict[str, Any]:
    starts = [start for row in rows if (start := _row_start(row)) is not None]
    ends = [end for row in rows if (end := _row_end(row)) is not None]
    wall_ms = 0
    if starts and ends:
        wall_ms = max(0, int((max(ends) - min(starts)).total_seconds() * 1000))
    return {
        "event": event_type,
        "source": source,
        "procs": len(rows),
        "cpu_seconds": round(sum(_duration_ms(row) for row in rows) / 1000, 3),
        "wall_ms": wall_ms,
    }


def _event_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    legacy: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        event_type = _event_type(row)
        uid = row.get("event_uid")
        if isinstance(uid, str) and uid:
            grouped.setdefault((event_type, uid), []).append(row)
        else:
            legacy.setdefault(event_type, []).append(row)

    groups = [_event_group_summary(event_type, group, "event_uid") for (event_type, _uid), group in sorted(grouped.items())]
    for event_type, event_rows in sorted(legacy.items()):
        sorted_rows = sorted(event_rows, key=lambda row: _row_end(row) or datetime.min.replace(tzinfo=timezone.utc))
        window_rows: list[dict[str, Any]] = []
        window_start: datetime | None = None
        for row in sorted_rows:
            end = _row_end(row)
            if end is None:
                continue
            if window_start is None or (end - window_start).total_seconds() > DASHBOARD_WINDOW_SECONDS:
                if window_rows:
                    groups.append(_event_group_summary(event_type, window_rows, "window_2s"))
                window_rows = [row]
                window_start = end
            else:
                window_rows.append(row)
        if window_rows:
            groups.append(_event_group_summary(event_type, window_rows, "window_2s"))
    return groups


def _herd_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups_by_event: dict[str, list[dict[str, Any]]] = {}
    for group in _event_groups(rows):
        groups_by_event.setdefault(group["event"], []).append(group)
    summary = []
    for event_type in sorted(groups_by_event):
        groups = groups_by_event[event_type]
        procs = [float(group["procs"]) for group in groups]
        cpu = [float(group["cpu_seconds"]) for group in groups]
        wall = [float(group["wall_ms"]) for group in groups]
        summary.append(
            {
                "event": event_type,
                "events": len(groups),
                "uid_groups": sum(1 for group in groups if group["source"] == "event_uid"),
                "window_groups": sum(1 for group in groups if group["source"] == "window_2s"),
                "p50_procs": percentile(procs, 0.5),
                "p90_procs": percentile(procs, 0.9),
                "p50_cpu_seconds": percentile(cpu, 0.5),
                "p90_cpu_seconds": percentile(cpu, 0.9),
                "p50_wall_ms": percentile(wall, 0.5),
                "p90_wall_ms": percentile(wall, 0.9),
            }
        )
    return summary


def _latency_rows(rows: list[dict[str, Any]], key_name: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[float]] = {}
    for row in rows:
        if key_name == "event":
            name = _event_type(row)
        else:
            name = f"{row.get('harness') or ''} {row.get('hook') or ''}/{row.get('script') or ''}".strip()
        grouped.setdefault(name, []).append(float(_duration_ms(row)))
    return [
        {
            key_name: name,
            "runs": len(values),
            "p50_ms": percentile(values, 0.5),
            "p90_ms": percentile(values, 0.9),
        }
        for name, values in sorted(grouped.items())
    ]


def _daily_outcomes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, int]] = {}
    for row in rows:
        ts = parse_ts(row.get("ts"))
        if ts is None:
            continue
        entry = grouped.setdefault(ts.date().isoformat(), {outcome: 0 for outcome in OUTCOMES})
        outcome = row.get("outcome")
        if outcome in OUTCOMES:
            entry[str(outcome)] += 1
    return [{"date": date, **counts} for date, counts in sorted(grouped.items())]


def _per_hook(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(key(row), []).append(row)
    return [summarize_one(item, grouped[item]) for item in sorted(grouped)]


def build_dashboard_summary(root: Path, since: timedelta, now: datetime) -> dict[str, Any]:
    threshold = now - since
    run_rows, run_malformed, run_warnings = _read_dashboard_rows(root / "runs.jsonl", threshold)
    event_rows, event_malformed, event_warnings = _read_dashboard_event_rows(root, threshold)
    newest_ts = max((ts for row in run_rows if (ts := parse_ts(row.get("ts"))) is not None), default=None)
    runs_path = root / "runs.jsonl"
    try:
        runs_size = runs_path.stat().st_size
        runs_exists = True
    except FileNotFoundError:
        runs_size = 0
        runs_exists = False
    except OSError as exc:
        runs_size = 0
        runs_exists = False
        run_warnings.append(f"unchecked: {runs_path}: {exc}")
    per_hook = _per_hook(run_rows)
    failures = sum(1 for row in run_rows if row.get("outcome") in FAILURE_OUTCOMES)
    timeouts = sum(1 for row in run_rows if row.get("outcome") == "timed_out")
    crashes = sum(1 for row in run_rows if row.get("outcome") == "crashed")
    total = len(run_rows)
    return {
        "generated_at": now.isoformat(),
        "since_seconds": int(since.total_seconds()),
        "metrics_dir": str(root),
        "herd": _herd_summary(run_rows),
        "latency": {
            "by_event": _latency_rows(run_rows, "event"),
            "by_hook": _latency_rows(run_rows, "hook"),
        },
        "health": {
            "daily_outcomes": _daily_outcomes(run_rows),
            "rates": {
                "runs": total,
                "timeout_rate": round(timeouts / total, 3) if total else 0.0,
                "crash_rate": round(crashes / total, 3) if total else 0.0,
                "failure_rate": round(failures / total, 3) if total else 0.0,
            },
            "per_hook": per_hook,
        },
        "ledger": {
            "runs_jsonl": str(runs_path),
            "runs_exists": runs_exists,
            "runs_bytes": runs_size,
            "runs_rows": total,
            "runs_malformed_rows": run_malformed,
            "runs_warnings": run_warnings,
            "events_rows": len(event_rows),
            "events_malformed_rows": event_malformed,
            "events_warnings": event_warnings,
            "scan_lag_seconds": round((now - newest_ts).total_seconds(), 3) if newest_ts is not None else None,
        },
    }


def _fmt(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def _html_table(headers: list[str], rows: list[list[object]]) -> str:
    head = "".join(f"<th>{html.escape(header)}</th>" for header in headers)
    body = []
    for row in rows:
        body.append("<tr>" + "".join(f"<td>{html.escape(_fmt(value))}</td>" for value in row) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def render_dashboard_html(summary: dict[str, Any]) -> str:
    herd = _html_table(
        ["event", "events", "uid groups", "2s fallback", "p50 procs", "p90 procs", "p50 CPU-s", "p90 CPU-s", "p50 wall ms"],
        [
            [
                row["event"],
                row["events"],
                row["uid_groups"],
                row["window_groups"],
                row["p50_procs"],
                row["p90_procs"],
                row["p50_cpu_seconds"],
                row["p90_cpu_seconds"],
                row["p50_wall_ms"],
            ]
            for row in summary["herd"]
        ],
    )
    latency_event = _html_table(
        ["event", "runs", "p50 ms", "p90 ms"],
        [[row["event"], row["runs"], row["p50_ms"], row["p90_ms"]] for row in summary["latency"]["by_event"]],
    )
    latency_hook = _html_table(
        ["hook", "runs", "p50 ms", "p90 ms"],
        [[row["hook"], row["runs"], row["p50_ms"], row["p90_ms"]] for row in summary["latency"]["by_hook"]],
    )
    daily = _html_table(
        ["date", *OUTCOMES],
        [[row["date"], *[row[outcome] for outcome in OUTCOMES]] for row in summary["health"]["daily_outcomes"]],
    )
    hooks = _html_table(
        ["harness", "hook/script", "runs", "spoke", "silent", "blocked", "crashed", "caught_error", "timed_out", "p95 ms", "last error"],
        [
            [
                row["harness"],
                f"{row['hook']}/{row['script']}",
                row["runs"],
                row["spoke"],
                row["silent"],
                row["blocked"],
                row["crashed"],
                row["caught_error"],
                row["timed_out"],
                row["p95_ms"],
                row["last_error"],
            ]
            for row in summary["health"]["per_hook"]
        ],
    )
    ledger = summary["ledger"]
    ledger_table = _html_table(
        ["metric", "value"],
        [
            ["runs.jsonl", ledger["runs_jsonl"]],
            ["runs.jsonl size", ledger["runs_bytes"]],
            ["runs rows", ledger["runs_rows"]],
            ["runs malformed", ledger["runs_malformed_rows"]],
            ["events rows", ledger["events_rows"]],
            ["events malformed", ledger["events_malformed_rows"]],
            ["fold freshness", summary["generated_at"]],
            ["scan lag seconds", ledger["scan_lag_seconds"]],
        ],
    )
    rates = summary["health"]["rates"]
    empty = "<p>No runner metrics rows in this window.</p>" if ledger["runs_rows"] == 0 else ""
    warnings = [*ledger["runs_warnings"], *ledger["events_warnings"]]
    warning_html = "".join(f"<li>{html.escape(warning)}</li>" for warning in warnings)
    warning_block = f"<section><h2>Warnings</h2><ul>{warning_html}</ul></section>" if warnings else ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Hook Runner Dashboard</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 2rem; color: #202124; background: #f8f9fa; }}
h1, h2, h3 {{ margin: 0 0 0.75rem; }}
section {{ margin: 0 0 2rem; }}
table {{ border-collapse: collapse; width: 100%; background: white; margin: 0 0 1rem; }}
th, td {{ border: 1px solid #d9dce1; padding: 0.45rem 0.55rem; text-align: left; vertical-align: top; }}
th {{ background: #eef1f4; }}
.rates {{ display: flex; gap: 1rem; flex-wrap: wrap; margin: 0 0 1rem; }}
.rates span {{ background: white; border: 1px solid #d9dce1; padding: 0.45rem 0.55rem; }}
</style>
</head>
<body>
<h1>Hook Runner Dashboard</h1>
{empty}
<section><h2>Herd</h2>{herd}</section>
<section><h2>Latency</h2><h3>By Event</h3>{latency_event}<h3>By Hook</h3>{latency_hook}</section>
<section><h2>Health</h2><div class="rates"><span>Timeout rate: {html.escape(_fmt(rates["timeout_rate"]))}</span><span>Crash rate: {html.escape(_fmt(rates["crash_rate"]))}</span><span>Failure rate: {html.escape(_fmt(rates["failure_rate"]))}</span></div><h3>Daily Outcome Mix</h3>{daily}<h3>Per Hook</h3>{hooks}</section>
<section><h2>Ledger</h2>{ledger_table}</section>
{warning_block}
</body>
</html>
"""


def write_dashboard(root: Path, since: timedelta, now: datetime) -> tuple[Path, Path, list[str]]:
    summary = build_dashboard_summary(root, since, now)
    summary_path = root / "summary.json"
    html_path = root / "dashboard.html"
    try:
        root.mkdir(parents=True, exist_ok=True)
        with summary_path.open("w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2, sort_keys=True)
            handle.write("\n")
        with summary_path.open(encoding="utf-8") as handle:
            rendered_summary = json.load(handle)
        with html_path.open("w", encoding="utf-8") as handle:
            handle.write(render_dashboard_html(rendered_summary))
    except (OSError, TypeError, ValueError) as exc:
        raise RuntimeError(f"could not write dashboard under {root}: {exc}") from exc
    warnings = [*summary["ledger"]["runs_warnings"], *summary["ledger"]["events_warnings"]]
    return summary_path, html_path, warnings


def event_key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row.get("hook") or ""), str(row.get("rule_id") or "")


def _closed_outcomes(rows: list[dict[str, Any]]) -> list[str]:
    ordered = sorted(
        (
            row
            for row in rows
            if row.get("action") == "followup"
            and row.get("outcome") in {"acted", "ignored", "overridden"}
        ),
        key=lambda row: parse_ts(row.get("ts")) or datetime.min.replace(tzinfo=timezone.utc),
    )
    return [str(row.get("outcome")) for row in ordered]


def event_summary_one(
    hook: str,
    rule_id: str,
    rows: list[dict[str, Any]],
    registry_data: tuple[dict[str, registry.HookRecord], registry.Thresholds],
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "hook": hook,
        "rule_id": rule_id,
        "fires": 0,
        "stopped": 0,
        "warned": 0,
        "acted": 0,
        "ignored": 0,
        "overridden": 0,
        "unchecked": 0,
        "crashes": 0,
        "p95_ms": None,
        "ignore_rate": None,
        "suggestion": "no change",
    }
    durations = []
    for row in rows:
        action = row.get("action")
        if action in {"stopped", "warned", "unchecked", "crashed"}:
            summary["fires"] += 1
        if action == "stopped":
            summary["stopped"] += 1
        elif action == "warned":
            summary["warned"] += 1
        elif action == "unchecked":
            summary["unchecked"] += 1
        elif action == "crashed":
            summary["crashes"] += 1
        if action == "followup":
            outcome = row.get("outcome")
            if outcome == "acted":
                summary["acted"] += 1
            elif outcome == "ignored":
                summary["ignored"] += 1
            elif outcome == "overridden":
                summary["overridden"] += 1
            elif outcome == "unchecked":
                summary["unchecked"] += 1
        duration = row.get("duration_ms")
        if action != "followup" and isinstance(duration, int) and not isinstance(duration, bool):
            durations.append(duration)
    summary["p95_ms"] = p95(durations)

    closed = summary["acted"] + summary["ignored"] + summary["overridden"]
    if closed:
        summary["ignore_rate"] = (summary["ignored"] + summary["overridden"]) / closed

    hooks, thresholds = registry_data
    record = hooks.get(hook)
    mode = record.mode if record is not None else ""
    why_mode = record.why_mode if record is not None else ""
    runs = summary["fires"]
    unchecked_rate = (summary["crashes"] + summary["unchecked"]) / runs if runs else 0.0
    closed_outcomes = _closed_outcomes(rows)
    recent_closed = closed_outcomes[-thresholds.min_closed_findings :]
    recent_ignore_rate = (
        (recent_closed.count("ignored") + recent_closed.count("overridden")) / len(recent_closed)
        if len(recent_closed) >= thresholds.min_closed_findings
        else None
    )

    if (
        mode == "warn"
        and (summary["ignore_rate"] is not None and summary["ignore_rate"] > thresholds.review_min_ignore_rate)
    ) or unchecked_rate > thresholds.review_min_unchecked_rate:
        summary["suggestion"] = "review or turn off"
    elif closed < thresholds.min_closed_findings:
        summary["suggestion"] = "not enough data"
    elif (
        mode == "stop"
        and recent_ignore_rate is not None
        and recent_ignore_rate > thresholds.demote_min_ignore_rate
    ):
        summary["suggestion"] = "stop to warn"
    elif (
        mode == "warn"
        and summary["ignore_rate"] is not None
        and summary["ignore_rate"] <= thresholds.promote_max_ignore_rate
        and why_mode in {"attention", "outward"}
    ):
        summary["suggestion"] = "warn to stop"
    return summary


def build_event_report(
    rows: list[dict[str, Any]],
    malformed: int,
    warnings: list[str],
    registry_data: tuple[dict[str, registry.HookRecord], registry.Thresholds],
) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        hook, rule_id = event_key(row)
        if not hook or not rule_id:
            continue
        grouped.setdefault((hook, rule_id), []).append(row)
    summaries = [
        event_summary_one(hook, rule_id, grouped[(hook, rule_id)], registry_data)
        for hook, rule_id in sorted(grouped)
    ]
    return {
        "window_rows": len(rows),
        "malformed_rows": malformed,
        "warnings": warnings,
        "rules": summaries,
    }


def format_event_table(report: dict[str, Any]) -> str:
    lines = []
    for warning in report["warnings"]:
        lines.append(warning)
    if report["malformed_rows"]:
        lines.append(f"skipped {report['malformed_rows']} malformed event row(s)")
    lines.append(
        "hook rule_id fires stopped warned acted ignored overridden unchecked crashes p95_ms ignore_rate suggestion"
    )
    for row in report["rules"]:
        lines.append(
            f"{row['hook']} {row['rule_id']} {row['fires']} {row['stopped']} {row['warned']} "
            f"{row['acted']} {row['ignored']} {row['overridden']} {row['unchecked']} {row['crashes']} "
            f"{row['p95_ms'] if row['p95_ms'] is not None else '-'} {format_rate(row['ignore_rate'])} "
            f"{row['suggestion']}"
        )
    return "\n".join(lines) + "\n"


JUDGE_STAGES = ("judge_skipped", "judge_queued", "judge_finished")
VERDICTS = ("hit", "clean", "unchecked")
LEAKS = ("no_transcript", "stuck", "undelivered", "undelivered_hits")


def is_delivery(row: dict[str, Any]) -> bool:
    return row.get("harness") == "judge" and row.get("mode_source") == "judge" and row.get("action") in VERDICTS


def _judge_summary(hook: str) -> dict[str, Any]:
    return {
        "hook": hook,
        "skipped": {},
        "queued": 0,
        "finished": {verdict: 0 for verdict in VERDICTS},
        "delivered": {verdict: 0 for verdict in VERDICTS},
        **{leak: 0 for leak in LEAKS},
    }


def build_judge_report(
    rows: list[dict[str, Any]],
    malformed: int,
    warnings: list[str],
    now: datetime,
    grace: timedelta,
) -> dict[str, Any]:
    summaries: dict[str, dict[str, Any]] = {}
    jobs: dict[str, dict[str, Any]] = {}
    for row in rows:
        action = row.get("action")
        if action not in JUDGE_STAGES and not is_delivery(row):
            continue
        hook = str(row.get("hook") or "")
        summary = summaries.setdefault(hook, _judge_summary(hook))
        reason = str(row.get("reason") or "")
        ts = parse_ts(row.get("ts"))
        job = jobs.setdefault(str(row.get("finding_id") or ""), {"hook": hook})
        if action == "judge_skipped":
            summary["skipped"][reason] = summary["skipped"].get(reason, 0) + 1
        elif action == "judge_queued":
            summary["queued"] += 1
            if reason == "no_transcript":
                summary["no_transcript"] += 1
            job["queued"] = ts
        elif action == "judge_finished":
            verdict = reason if reason in VERDICTS else "unchecked"
            summary["finished"][verdict] += 1
            job["finished"] = ts
            job["verdict"] = verdict
        else:
            summary["delivered"][str(action)] += 1
            job["delivered"] = ts
    for job in jobs.values():
        summary = summaries[job["hook"]]
        queued, finished = job.get("queued"), job.get("finished")
        if queued is not None and finished is None and now - queued > grace:
            summary["stuck"] += 1
        if finished is not None and "delivered" not in job and now - finished > grace:
            summary["undelivered"] += 1
            if job.get("verdict") == "hit":
                summary["undelivered_hits"] += 1
    ordered = [summaries[hook] for hook in sorted(summaries)]
    return {
        "window_rows": len(rows),
        "malformed_rows": malformed,
        "warnings": warnings,
        "grace_seconds": int(grace.total_seconds()),
        "hooks": ordered,
        "leaks": sum(summary[leak] for summary in ordered for leak in ("no_transcript", "stuck", "undelivered")),
    }


def _counts(values: dict[str, int]) -> str:
    return ",".join(f"{name}={count}" for name, count in sorted(values.items())) or "-"


def format_judge_table(report: dict[str, Any]) -> str:
    lines = list(report["warnings"])
    if report["malformed_rows"]:
        lines.append(f"skipped {report['malformed_rows']} malformed event row(s)")
    lines.append("hook skipped queued finished delivered " + " ".join(LEAKS))
    for row in report["hooks"]:
        lines.append(
            f"{row['hook']} {_counts(row['skipped'])} {row['queued']} {_counts(row['finished'])} "
            f"{_counts(row['delivered'])} " + " ".join(str(row[leak]) for leak in LEAKS)
        )
    if report["leaks"]:
        lines.append(
            f"LEAK: {report['leaks']} judge job(s) queued with no transcript, stuck, or never delivered "
            f"after {report['grace_seconds']}s"
        )
    return "\n".join(lines) + "\n"


HARNESSES = ("claude", "cursor", "codex")


def build_skill_report(rows: list[dict[str, Any]], malformed: int, warnings: list[str], home: str) -> dict[str, Any]:
    installed: dict[str, set[str]] = {}
    for harness in HARNESSES:
        names = skill_detect.installed_skills(harness, home)
        if names is None:
            warnings.append(f"unchecked: {harness} skill folders unreadable")
        installed[harness] = names or set()
    skills: dict[str, dict[str, Any]] = {}

    def entry(name: str) -> dict[str, Any]:
        return skills.setdefault(name, {"skill": name, **{h: 0 for h in HARNESSES}, "sources": {}, "installed": []})

    for harness, names in installed.items():
        for name in names:
            entry(name)["installed"].append(harness)
    unchecked = 0
    for row in rows:
        if row.get("hook") != "skill-usage-log":
            continue
        if row.get("action") == "skill_usage_unchecked":
            unchecked += 1
            continue
        if row.get("action") != "skill_used" or not isinstance(row.get("skill"), str):
            continue
        item = entry(row["skill"])
        harness = str(row.get("harness") or "")
        if harness in HARNESSES:
            item[harness] += 1
        source = str(row.get("reason") or "")
        item["sources"][source] = item["sources"].get(source, 0) + 1
    ordered = sorted(skills.values(), key=lambda item: (-sum(item[h] for h in HARNESSES), item["skill"]))
    return {"malformed_rows": malformed, "warnings": warnings, "unchecked_runs": unchecked, "skills": ordered}


def format_skill_table(report: dict[str, Any]) -> str:
    lines = list(report["warnings"])
    if report["malformed_rows"]:
        lines.append(f"skipped {report['malformed_rows']} malformed event row(s)")
    if report["unchecked_runs"]:
        lines.append(f"unchecked: {report['unchecked_runs']} skill-usage-log run(s) could not read their input")
    lines.append("skill " + " ".join(HARNESSES) + " sources")
    for item in report["skills"]:
        if not any(item[h] for h in HARNESSES):
            lines.append(f"{item['skill']} no record")
            continue
        lines.append(f"{item['skill']} " + " ".join(str(item[h]) for h in HARNESSES) + f" {_counts(item['sources'])}")
    return "\n".join(lines) + "\n"


def transcript_paths(home: Path) -> tuple[list[Path], list[str]]:
    root = home / ".claude" / "projects"
    if not root.exists():
        return [], []
    try:
        project_dirs = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError as exc:
        return [], [f"unchecked transcripts: {root}: {exc}"]
    paths: list[Path] = []
    warnings: list[str] = []
    for project_dir in project_dirs:
        try:
            paths.extend(sorted(project_dir.glob("*.jsonl")))
        except OSError as exc:
            warnings.append(f"unchecked transcripts: {project_dir}: {exc}")
    return paths, warnings


def read_hook_cancel_rows(paths: list[Path], threshold: datetime) -> tuple[list[dict[str, Any]], int, list[str]]:
    rows: list[dict[str, Any]] = []
    malformed = 0
    warnings: list[str] = []
    for path in paths:
        try:
            with path.open(encoding="utf-8") as handle:
                lines = handle.readlines()
        except OSError as exc:
            warnings.append(f"unchecked transcript: {path}: {exc}")
            continue
        for line in lines:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if not isinstance(obj, dict):
                malformed += 1
                continue
            attachment = obj.get("attachment")
            if not isinstance(attachment, dict) or attachment.get("type") != "hook_cancelled":
                continue
            if not attachment.get("timedOut"):
                continue
            ts = parse_ts(obj.get("timestamp"))
            if ts is None or ts < threshold:
                continue
            command = attachment.get("command")
            hook = ""
            if isinstance(command, str) and command.strip():
                target = command.split()[-1]
                hook = target.split("/")[0]
            rows.append({"session_id": str(obj.get("sessionId") or ""), "hook": hook, "ts": ts})
    return rows, malformed, warnings


def build_harness_gap_report(
    cancel_rows: list[dict[str, Any]],
    cancel_malformed: int,
    warnings: list[str],
    timed_out_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    cancel_counts: dict[tuple[str, str], int] = {}
    for row in cancel_rows:
        cancel_key = (row["session_id"], row["hook"])
        cancel_counts[cancel_key] = cancel_counts.get(cancel_key, 0) + 1
    run_counts: dict[tuple[str, str], int] = {}
    for row in timed_out_rows:
        run_key = (str(row.get("session_id") or ""), str(row.get("hook") or ""))
        run_counts[run_key] = run_counts.get(run_key, 0) + 1
    per_hook: dict[str, dict[str, int]] = {}
    for (session_id, hook), count in cancel_counts.items():
        entry = per_hook.setdefault(hook, {"cancelled": 0, "matched": 0})
        entry["cancelled"] += count
        entry["matched"] += min(count, run_counts.get((session_id, hook), 0))
    hooks = []
    for hook in sorted(per_hook):
        entry = per_hook[hook]
        hooks.append({"hook": hook, "cancelled": entry["cancelled"], "matched": entry["matched"], "gap": entry["cancelled"] - entry["matched"]})
    return {
        "cancel_malformed_rows": cancel_malformed,
        "warnings": warnings,
        "hooks": hooks,
        "total_cancelled": sum(row["cancelled"] for row in hooks),
        "total_matched": sum(row["matched"] for row in hooks),
        "total_gap": sum(row["gap"] for row in hooks),
    }


def format_harness_gap_table(report: dict[str, Any]) -> str:
    lines = list(report["warnings"])
    if report["cancel_malformed_rows"]:
        lines.append(f"skipped {report['cancel_malformed_rows']} malformed transcript row(s)")
    lines.append("hook cancelled matched gap")
    for row in report["hooks"]:
        lines.append(f"{row['hook']} {row['cancelled']} {row['matched']} {row['gap']}")
    lines.append(
        f"TOTAL cancelled={report['total_cancelled']} matched={report['total_matched']} gap={report['total_gap']}"
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", default="7d")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--html", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--events", action="store_true", default=True)
    mode.add_argument("--runs", action="store_true")
    mode.add_argument("--judge", action="store_true")
    mode.add_argument("--skills", action="store_true")
    mode.add_argument("--harness-gap", action="store_true")
    parser.add_argument("--grace", default="1h")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        since = parse_since(args.since)
        grace = parse_since(args.grace)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.html:
        try:
            summary_path, html_path, warnings = write_dashboard(metrics_dir(), since, datetime.now(timezone.utc))
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(f"wrote {summary_path}")
        print(f"wrote {html_path}")
        for warning in warnings:
            print(warning)
        return 2 if warnings else 0
    if args.harness_gap:
        threshold = datetime.now(timezone.utc) - since
        home = Path(os.path.expanduser("~"))
        paths, path_warnings = transcript_paths(home)
        cancel_rows, cancel_malformed, cancel_warnings = read_hook_cancel_rows(paths, threshold)
        warnings = path_warnings + cancel_warnings
        rows, malformed, error = read_rows(metrics_path(), threshold)
        if error is not None:
            print(error)
            return 2
        timed_out_rows = [row for row in (rows or []) if row.get("outcome") == "timed_out"]
        report = build_harness_gap_report(cancel_rows, cancel_malformed, warnings, timed_out_rows)
        if args.json:
            print(json.dumps(report, sort_keys=True))
        else:
            print(format_harness_gap_table(report), end="")
        return 2 if report["warnings"] else 0
    if args.skills:
        rows, malformed, warnings = read_event_rows(metrics_dir(), datetime.now(timezone.utc) - since)
        if rows is None:
            for warning in warnings:
                print(warning)
            return 2
        report = build_skill_report(rows, malformed, warnings, os.path.expanduser("~"))
        if args.json:
            print(json.dumps(report, sort_keys=True))
        else:
            print(format_skill_table(report), end="")
        return 2 if report["warnings"] or report["unchecked_runs"] else 0
    if args.judge:
        now = datetime.now(timezone.utc)
        rows, malformed, warnings = read_event_rows(metrics_dir(), now - since)
        if rows is None:
            for warning in warnings:
                print(warning)
            return 2
        report = build_judge_report(rows, malformed, warnings, now, grace)
        if args.json:
            print(json.dumps(report, sort_keys=True))
        else:
            print(format_judge_table(report), end="")
        if warnings:
            return 2
        return 1 if args.check and report["leaks"] else 0
    if not args.runs:
        try:
            registry_data = registry.load_registry()
        except registry.RegistryError as exc:
            print(f"unchecked registry: {exc}")
            return 2
        rows, malformed, warnings = read_event_rows(metrics_dir(), datetime.now(timezone.utc) - since)
        if rows is None:
            for warning in warnings:
                print(warning)
            return 2
        report = build_event_report(rows, malformed, warnings, registry_data)
        if args.json:
            print(json.dumps(report, sort_keys=True))
        else:
            print(format_event_table(report), end="")
        return 2 if warnings else 0
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
