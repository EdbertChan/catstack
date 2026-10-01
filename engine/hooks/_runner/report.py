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
EVENT_WINDOW_SECONDS = 2.0


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
    return ordered[index]


def rounded(value: float | None, digits: int = 3) -> float | None:
    if value is None:
        return None
    return round(value, digits)


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


class DashboardFoldError(Exception):
    pass


def _read_dashboard_jsonl(path: Path, *, missing_ok: bool = False) -> tuple[list[dict[str, Any]], int, bool]:
    try:
        with path.open(encoding="utf-8") as handle:
            lines = handle.readlines()
    except FileNotFoundError:
        if missing_ok:
            return [], 0, False
        raise DashboardFoldError(f"could not read {path}: file not found")
    except OSError as exc:
        raise DashboardFoldError(f"could not read {path}: {exc}") from exc

    rows: list[dict[str, Any]] = []
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
        rows.append(row)
    return rows, malformed, True


def _duration_ms(row: dict[str, Any]) -> int | None:
    value = row.get("duration_ms")
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _event_type(row: dict[str, Any]) -> str:
    return str(row.get("event") or "unknown")


def _hook_name(row: dict[str, Any]) -> str:
    hook = str(row.get("hook") or "unknown")
    script = str(row.get("script") or "")
    return f"{hook}/{script}" if script else hook


def _event_group_key(row: dict[str, Any]) -> tuple[str, str, str]:
    event = _event_type(row)
    event_uid = row.get("event_uid")
    if isinstance(event_uid, str) and event_uid:
        return event, "event_uid", event_uid
    ts = parse_ts(row.get("ts"))
    if ts is None:
        bucket = "unknown"
    else:
        bucket = str(math.floor(ts.timestamp() / EVENT_WINDOW_SECONDS))
    session_id = str(row.get("session_id") or "")
    return event, "window", f"{session_id}:{bucket}"


def _group_run_events(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(_event_group_key(row), []).append(row)
    return groups


def _wall_ms(rows: list[dict[str, Any]]) -> int | None:
    starts: list[datetime] = []
    ends: list[datetime] = []
    for row in rows:
        ts = parse_ts(row.get("ts"))
        duration = _duration_ms(row)
        if ts is None or duration is None:
            continue
        starts.append(ts)
        ends.append(ts + timedelta(milliseconds=duration))
    if not starts or not ends:
        return None
    return max(0, int((max(ends) - min(starts)).total_seconds() * 1000))


def _series_stats(values: list[float], digits: int = 3) -> dict[str, Any]:
    return {
        "p50": rounded(percentile(values, 0.50), digits),
        "p90": rounded(percentile(values, 0.90), digits),
    }


def build_dashboard_herd(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_event: dict[str, list[dict[str, Any]]] = {}
    grouping: dict[str, dict[str, int]] = {}
    for group_key, group_rows in _group_run_events(rows).items():
        event, group_type, _uid = group_key
        by_event.setdefault(event, []).append({"group_type": group_type, "rows": group_rows})
        grouping.setdefault(event, {"event_uid": 0, "window": 0})[group_type] += 1

    summaries: list[dict[str, Any]] = []
    for event in sorted(by_event):
        procs: list[float] = []
        cpu_seconds: list[float] = []
        wall_seconds: list[float] = []
        for group in by_event[event]:
            group_rows = group["rows"]
            procs.append(float(len(group_rows)))
            cpu_seconds.append(sum((_duration_ms(row) or 0) for row in group_rows) / 1000.0)
            wall = _wall_ms(group_rows)
            if wall is not None:
                wall_seconds.append(wall / 1000.0)
        summaries.append(
            {
                "event": event,
                "events": len(by_event[event]),
                "grouping": grouping[event],
                "procs_per_event": _series_stats(procs, 1),
                "cpu_seconds_per_event": _series_stats(cpu_seconds, 3),
                "wall_seconds_per_event": _series_stats(wall_seconds, 3),
            }
        )
    return summaries


def _latency_entry(name: str, durations: list[int]) -> dict[str, Any]:
    seconds = [value / 1000.0 for value in durations]
    stats = _series_stats(seconds, 3)
    return {"name": name, "runs": len(durations), "p50_seconds": stats["p50"], "p90_seconds": stats["p90"]}


def build_dashboard_latency(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_event: dict[str, list[int]] = {}
    by_hook: dict[str, list[int]] = {}
    for row in rows:
        duration = _duration_ms(row)
        if duration is None:
            continue
        by_event.setdefault(_event_type(row), []).append(duration)
        by_hook.setdefault(_hook_name(row), []).append(duration)
    return {
        "events": [_latency_entry(event, by_event[event]) for event in sorted(by_event)],
        "hooks": [_latency_entry(hook, by_hook[hook]) for hook in sorted(by_hook)],
    }


def build_dashboard_health(rows: list[dict[str, Any]]) -> dict[str, Any]:
    daily: dict[str, dict[str, int]] = {}
    for row in rows:
        ts = parse_ts(row.get("ts"))
        day = ts.date().isoformat() if ts is not None else "unknown"
        outcome = str(row.get("outcome") or "unknown")
        entry = daily.setdefault(day, {"total": 0, **{item: 0 for item in OUTCOMES}, "unknown": 0})
        entry["total"] += 1
        entry[outcome if outcome in OUTCOMES else "unknown"] += 1

    per_hook_rows = []
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(key(row), []).append(row)
    for item in sorted(grouped):
        per_hook_rows.append(summarize_one(item, grouped[item]))

    total = len(rows)
    timeouts = sum(1 for row in rows if row.get("outcome") == "timed_out")
    crashes = sum(1 for row in rows if row.get("outcome") == "crashed")
    return {
        "daily": [{"day": day, **daily[day]} for day in sorted(daily)],
        "timeout_rate": rounded(timeouts / total if total else 0.0, 4),
        "crash_rate": rounded(crashes / total if total else 0.0, 4),
        "per_hook": per_hook_rows,
    }


def build_dashboard_summary(root: Path, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    runs_path = root / "runs.jsonl"
    run_rows, run_malformed, runs_exists = _read_dashboard_jsonl(runs_path, missing_ok=True)
    event_files, event_warnings = event_paths(root)
    event_rows: list[dict[str, Any]] = []
    event_malformed = 0
    for path in event_files:
        rows, malformed, _exists = _read_dashboard_jsonl(path)
        event_rows.extend(rows)
        event_malformed += malformed

    parsed_run_ts = [ts for row in run_rows if (ts := parse_ts(row.get("ts"))) is not None]
    newest_run = max(parsed_run_ts) if parsed_run_ts else None
    try:
        runs_size = runs_path.stat().st_size if runs_exists else 0
    except OSError as exc:
        raise DashboardFoldError(f"could not stat {runs_path}: {exc}") from exc

    return {
        "schema": "catstack.hook.dashboard.v1",
        "generated_at": now.isoformat(),
        "metrics_dir": str(root),
        "inputs": {
            "runs_jsonl": {
                "path": str(runs_path),
                "exists": runs_exists,
                "size_bytes": runs_size,
                "rows": len(run_rows),
                "malformed_rows": run_malformed,
                "newest_ts": newest_run.isoformat() if newest_run is not None else None,
                "scan_lag_seconds": (
                    rounded(max(0.0, (now - newest_run).total_seconds()), 3)
                    if newest_run is not None
                    else None
                ),
            },
            "events_jsonl": {
                "files": [str(path) for path in event_files],
                "rows": len(event_rows),
                "malformed_rows": event_malformed,
                "warnings": event_warnings,
            },
        },
        "herd": build_dashboard_herd(run_rows),
        "latency": build_dashboard_latency(run_rows),
        "health": build_dashboard_health(run_rows),
    }


def _fmt_number(value: object, suffix: str = "") -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        text = f"{value:.3f}".rstrip("0").rstrip(".")
    else:
        text = str(value)
    return html.escape(text + suffix)


def _html_table(headers: list[str], rows: list[list[object]]) -> str:
    header_html = "".join(f"<th>{html.escape(header)}</th>" for header in headers)
    body = []
    for row in rows:
        cells = "".join(f"<td>{_fmt_number(value)}</td>" for value in row)
        body.append(f"<tr>{cells}</tr>")
    if not body:
        body.append(f"<tr><td colspan=\"{len(headers)}\">No rows</td></tr>")
    return f"<table><thead><tr>{header_html}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def render_dashboard_html(summary: dict[str, Any]) -> str:
    inputs = summary["inputs"]
    runs_input = inputs["runs_jsonl"]
    events_input = inputs["events_jsonl"]
    herd_rows = [
        [
            row["event"],
            row["events"],
            row["grouping"].get("event_uid", 0),
            row["grouping"].get("window", 0),
            row["procs_per_event"]["p50"],
            row["procs_per_event"]["p90"],
            row["cpu_seconds_per_event"]["p50"],
            row["cpu_seconds_per_event"]["p90"],
            row["wall_seconds_per_event"]["p50"],
            row["wall_seconds_per_event"]["p90"],
        ]
        for row in summary["herd"]
    ]
    latency_event_rows = [
        [row["name"], row["runs"], row["p50_seconds"], row["p90_seconds"]]
        for row in summary["latency"]["events"]
    ]
    latency_hook_rows = [
        [row["name"], row["runs"], row["p50_seconds"], row["p90_seconds"]]
        for row in summary["latency"]["hooks"]
    ]
    daily_rows = [
        [
            row["day"],
            row["total"],
            row["spoke"],
            row["silent"],
            row["blocked"],
            row["crashed"],
            row["caught_error"],
            row["timed_out"],
            row["unknown"],
        ]
        for row in summary["health"]["daily"]
    ]
    hook_rows = [
        [
            f"{row['harness']} {row['hook']}/{row['script']}",
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
    ]
    warnings = events_input.get("warnings") or []
    warnings_html = "".join(f"<li>{html.escape(str(warning))}</li>" for warning in warnings)
    if not warnings_html:
        warnings_html = "<li>None</li>"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Hook Runner Dashboard</title>
<style>
:root {{
  color-scheme: light;
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: #f6f7f9;
  color: #17202a;
}}
body {{ margin: 0; }}
main {{ max-width: 1180px; margin: 0 auto; padding: 28px; }}
h1 {{ font-size: 28px; margin: 0 0 4px; }}
h2 {{ font-size: 18px; margin: 28px 0 10px; }}
p {{ color: #4b5563; margin: 0 0 16px; }}
.stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; margin: 18px 0; }}
.stat {{ background: #ffffff; border: 1px solid #d9dee7; border-radius: 8px; padding: 12px; }}
.label {{ color: #667085; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }}
.value {{ font-size: 22px; font-weight: 650; margin-top: 4px; }}
table {{ width: 100%; border-collapse: collapse; background: #ffffff; border: 1px solid #d9dee7; margin-bottom: 18px; }}
th, td {{ border-bottom: 1px solid #e6e9ef; padding: 8px 10px; text-align: left; vertical-align: top; font-size: 13px; }}
th {{ background: #edf1f5; color: #243447; font-weight: 650; }}
tr:last-child td {{ border-bottom: 0; }}
.split {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 18px; }}
ul {{ background: #ffffff; border: 1px solid #d9dee7; border-radius: 8px; margin: 0; padding: 10px 28px; }}
</style>
</head>
<body>
<main>
<h1>Hook Runner Dashboard</h1>
<p>Generated {html.escape(str(summary["generated_at"]))} from {html.escape(str(summary["metrics_dir"]))}</p>
<section class="stats" aria-label="Ledger">
  <div class="stat"><div class="label">runs.jsonl size</div><div class="value">{_fmt_number(runs_input["size_bytes"])}</div></div>
  <div class="stat"><div class="label">run rows</div><div class="value">{_fmt_number(runs_input["rows"])}</div></div>
  <div class="stat"><div class="label">event rows</div><div class="value">{_fmt_number(events_input["rows"])}</div></div>
  <div class="stat"><div class="label">scan lag seconds</div><div class="value">{_fmt_number(runs_input["scan_lag_seconds"])}</div></div>
  <div class="stat"><div class="label">timeout rate</div><div class="value">{_fmt_number(summary["health"]["timeout_rate"])}</div></div>
  <div class="stat"><div class="label">crash rate</div><div class="value">{_fmt_number(summary["health"]["crash_rate"])}</div></div>
</section>
<h2>Herd</h2>
{_html_table(["event", "events", "uid groups", "window groups", "p50 procs", "p90 procs", "p50 CPU-s", "p90 CPU-s", "p50 wall-s", "p90 wall-s"], herd_rows)}
<h2>Latency</h2>
<div class="split">
  <div>{_html_table(["event", "runs", "p50 s", "p90 s"], latency_event_rows)}</div>
  <div>{_html_table(["hook", "runs", "p50 s", "p90 s"], latency_hook_rows)}</div>
</div>
<h2>Health</h2>
{_html_table(["day", "total", "spoke", "silent", "blocked", "crashed", "caught_error", "timed_out", "unknown"], daily_rows)}
{_html_table(["hook", "runs", "spoke", "silent", "blocked", "crashed", "caught_error", "timed_out", "p95_ms", "last_error"], hook_rows)}
<h2>Ledger</h2>
{_html_table(["artifact", "value"], [
    ["runs exists", runs_input["exists"]],
    ["runs malformed", runs_input["malformed_rows"]],
    ["events files", len(events_input["files"])],
    ["events malformed", events_input["malformed_rows"]],
    ["fold freshness", summary["generated_at"]],
    ["newest run", runs_input["newest_ts"]],
])}
<ul>{warnings_html}</ul>
</main>
</body>
</html>
"""


def write_dashboard_outputs(root: Path, summary: dict[str, Any]) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    summary_path = root / "summary.json"
    html_path = root / "dashboard.html"
    try:
        with summary_path.open("w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2, sort_keys=True)
            handle.write("\n")
        html_text = render_dashboard_html(summary)
        with html_path.open("w", encoding="utf-8") as handle:
            handle.write(html_text)
    except OSError as exc:
        raise DashboardFoldError(f"could not write dashboard outputs under {root}: {exc}") from exc
    return summary_path, html_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", default="7d")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--html", action="store_true", help="write summary.json and dashboard.html for the metrics directory")
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
        root = metrics_dir()
        try:
            summary = build_dashboard_summary(root)
            summary_path, html_path = write_dashboard_outputs(root, summary)
        except DashboardFoldError as exc:
            print(f"dashboard fold failed: {exc}", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps({"summary": str(summary_path), "html": str(html_path)}, sort_keys=True))
        else:
            print(f"wrote {summary_path}")
            print(f"wrote {html_path}")
        return 0
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
