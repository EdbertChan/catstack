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
HERD_WINDOW_SECONDS = 2


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


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * fraction) - 1)
    return ordered[index]


def format_rate(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}"


def format_decimal(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.1f}"


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


def _scorecard_phase(row: dict[str, Any]) -> str:
    dispatch_path = row.get("dispatch_path")
    return "after" if isinstance(dispatch_path, str) and dispatch_path else "before"


def _duration_ms(row: dict[str, Any]) -> int | None:
    duration = row.get("duration_ms")
    if isinstance(duration, int) and not isinstance(duration, bool):
        return duration
    return None


def _event_group_key(row: dict[str, Any], index: int) -> tuple[str, str, str, str]:
    phase = _scorecard_phase(row)
    event = str(row.get("event") or "(unknown)")
    session_id = str(row.get("session_id") or "")
    event_uid = row.get("event_uid")
    uid = str(event_uid) if isinstance(event_uid, str) and event_uid else f"row-{index}"
    return phase, event, session_id, uid


def _group_wall_ms(rows: list[dict[str, Any]]) -> int:
    starts = []
    ends = []
    fallback_total = 0
    for row in rows:
        duration = _duration_ms(row) or 0
        fallback_total += duration
        end = parse_ts(row.get("ts"))
        if end is None:
            continue
        starts.append(end - timedelta(milliseconds=duration))
        ends.append(end)
    if starts and ends:
        return max(0, int((max(ends) - min(starts)).total_seconds() * 1000))
    return fallback_total


def _group_procs(rows: list[dict[str, Any]], phase: str) -> int:
    if phase == "after":
        fallback = sum(1 for row in rows if row.get("dispatch_path") == "subprocess_fallback")
        return 1 + fallback
    return len(rows)


def build_scorecard(rows: list[dict[str, Any]], malformed: int, warnings: list[str]) -> dict[str, Any]:
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for index, row in enumerate(rows):
        groups.setdefault(_event_group_key(row, index), []).append(row)

    event_groups: dict[tuple[str, str], list[list[dict[str, Any]]]] = {}
    for (phase, event, _session_id, _uid), group_rows in groups.items():
        event_groups.setdefault((phase, event), []).append(group_rows)

    scorecard_rows = []
    for (phase, event), grouped_rows in sorted(event_groups.items()):
        flat = [row for group_rows in grouped_rows for row in group_rows]
        detector_runs = len(flat)
        events = len(grouped_rows)
        procs = sum(_group_procs(group_rows, phase) for group_rows in grouped_rows)
        cpu_ms = sum(_duration_ms(row) or 0 for row in flat)
        wall_ms = sum(_group_wall_ms(group_rows) for group_rows in grouped_rows)
        timeouts = sum(1 for row in flat if row.get("outcome") == "timed_out")
        crashes = sum(1 for row in flat if row.get("outcome") in {"crashed", "caught_error"})
        spoke = sum(1 for row in flat if row.get("outcome") == "spoke")
        scorecard_rows.append(
            {
                "phase": phase,
                "event": event,
                "events": events,
                "detector_runs": detector_runs,
                "procs_per_event": procs / events if events else None,
                "cpu_ms_per_event": cpu_ms / events if events else None,
                "wall_ms_per_event": wall_ms / events if events else None,
                "timeout_rate": timeouts / detector_runs if detector_runs else None,
                "crash_rate": crashes / detector_runs if detector_runs else None,
                "spoke_rate": spoke / detector_runs if detector_runs else None,
            }
        )
    return {"malformed_rows": malformed, "warnings": warnings, "scorecard": scorecard_rows}


def format_scorecard_table(report: dict[str, Any]) -> str:
    lines = list(report["warnings"])
    if report["malformed_rows"]:
        lines.append(f"skipped {report['malformed_rows']} malformed row(s)")
    lines.append(
        "phase event events detector_runs procs/event cpu_ms/event wall_ms/event timeout% crash% spoke-rate"
    )
    for row in report["scorecard"]:
        timeout_pct = row["timeout_rate"] * 100 if row["timeout_rate"] is not None else None
        crash_pct = row["crash_rate"] * 100 if row["crash_rate"] is not None else None
        lines.append(
            f"{row['phase']} {row['event']} {row['events']} {row['detector_runs']} "
            f"{format_decimal(row['procs_per_event'])} {format_decimal(row['cpu_ms_per_event'])} "
            f"{format_decimal(row['wall_ms_per_event'])} {format_decimal(timeout_pct)} "
            f"{format_decimal(crash_pct)} {format_rate(row['spoke_rate'])}"
        )
    return "\n".join(lines) + "\n"


def _round(value: float | None, digits: int = 3) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _dashboard_read_rows(path: Path, threshold: datetime) -> tuple[list[dict[str, Any]], int, str | None]:
    if not path.exists():
        return [], 0, None
    rows, malformed, error = read_rows(path, threshold)
    return rows or [], malformed, error


def _dashboard_read_event_rows(root: Path, threshold: datetime) -> tuple[list[dict[str, Any]], int, list[str]]:
    paths, warnings = event_paths(root)
    if not paths:
        return [], 0, warnings
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


def _event_type(row: dict[str, Any]) -> str:
    return str(row.get("event") or "unknown")


def _herd_group_key(row: dict[str, Any]) -> tuple[str, str, str]:
    event = _event_type(row)
    event_uid = row.get("event_uid")
    if isinstance(event_uid, str) and event_uid:
        return event, "event_uid", event_uid
    ts = parse_ts(row.get("ts"))
    bucket = 0 if ts is None else math.floor(ts.timestamp() / HERD_WINDOW_SECONDS)
    return event, "window", str(bucket)


def _latency_summary(name: str, durations: list[int]) -> dict[str, Any]:
    values = [float(duration) for duration in durations]
    return {
        "name": name,
        "runs": len(values),
        "p50_ms": _round(percentile(values, 0.50), 1),
        "p90_ms": _round(percentile(values, 0.90), 1),
    }


def _build_herd(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(_herd_group_key(row), []).append(row)

    by_event: dict[str, list[dict[str, Any]]] = {}
    for (event, method, _group_id), group_rows in grouped.items():
        cpu_seconds = 0.0
        for row in group_rows:
            duration = row.get("duration_ms")
            if isinstance(duration, int) and not isinstance(duration, bool):
                cpu_seconds += duration / 1000
        by_event.setdefault(event, []).append(
            {
                "method": method,
                "procs": len(group_rows),
                "cpu_seconds": cpu_seconds,
            }
        )

    event_types = []
    for event in sorted(by_event):
        groups = by_event[event]
        procs = [float(group["procs"]) for group in groups]
        cpu_seconds = [float(group["cpu_seconds"]) for group in groups]
        event_uid_groups = sum(1 for group in groups if group["method"] == "event_uid")
        window_groups = len(groups) - event_uid_groups
        event_types.append(
            {
                "event": event,
                "events": len(groups),
                "event_uid_groups": event_uid_groups,
                "window_groups": window_groups,
                "p50_procs_per_event": _round(percentile(procs, 0.50), 1),
                "p90_procs_per_event": _round(percentile(procs, 0.90), 1),
                "p50_cpu_seconds_per_event": _round(percentile(cpu_seconds, 0.50), 3),
                "p90_cpu_seconds_per_event": _round(percentile(cpu_seconds, 0.90), 3),
            }
        )
    return {"event_types": event_types}


def _build_latency(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_event: dict[str, list[int]] = {}
    by_hook: dict[str, list[int]] = {}
    for row in rows:
        duration = row.get("duration_ms")
        if not isinstance(duration, int) or isinstance(duration, bool):
            continue
        by_event.setdefault(_event_type(row), []).append(duration)
        hook_name = "/".join(part for part in (str(row.get("hook") or ""), str(row.get("script") or "")) if part)
        by_hook.setdefault(hook_name or "unknown", []).append(duration)
    return {
        "event_types": [_latency_summary(event, by_event[event]) for event in sorted(by_event)],
        "hooks": [_latency_summary(hook, by_hook[hook]) for hook in sorted(by_hook)],
    }


def _build_health(run_report: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    daily: dict[str, dict[str, int]] = {}
    for row in rows:
        ts = parse_ts(row.get("ts"))
        if ts is None:
            continue
        date = ts.date().isoformat()
        entry = daily.setdefault(date, {outcome: 0 for outcome in OUTCOMES})
        outcome = row.get("outcome")
        if outcome in OUTCOMES:
            entry[str(outcome)] += 1
    daily_mix = [{"date": date, **daily[date]} for date in sorted(daily)]
    total = len(rows)
    timed_out = sum(1 for row in rows if row.get("outcome") == "timed_out")
    crashed = sum(1 for row in rows if row.get("outcome") == "crashed")
    return {
        "daily_outcome_mix": daily_mix,
        "rates": {
            "runs": total,
            "timeout_rate": _round(timed_out / total if total else 0.0),
            "crash_rate": _round(crashed / total if total else 0.0),
        },
        "hooks": run_report["registered"] + run_report["unregistered"],
        "blocked": run_report["blocked"],
        "failures": run_report["failures"],
        "config_warnings": run_report["config_warnings"],
    }


def build_dashboard_summary(
    rows: list[dict[str, Any]],
    run_malformed: int,
    event_rows: list[dict[str, Any]],
    event_malformed: int,
    event_warnings: list[str],
    registered: set[tuple[str, str, str]],
    config_warnings: list[str],
    root: Path,
    now: datetime,
) -> dict[str, Any]:
    run_report = build_report(registered, rows, run_malformed, config_warnings)
    timestamps = [ts for ts in (parse_ts(row.get("ts")) for row in rows) if ts is not None]
    newest = max(timestamps) if timestamps else None
    runs_path = root / "runs.jsonl"
    event_files, _event_path_warnings = event_paths(root)
    return {
        "schema": "catstack.hook.dashboard.v1",
        "generated_at": _isoformat(now),
        "herd": _build_herd(rows),
        "latency": _build_latency(rows),
        "health": _build_health(run_report, rows),
        "ledger": {
            "runs_jsonl_size_bytes": runs_path.stat().st_size if runs_path.exists() else 0,
            "runs_jsonl_exists": runs_path.exists(),
            "run_rows": len(rows),
            "malformed_run_rows": run_malformed,
            "event_files": len(event_files),
            "event_rows": len(event_rows),
            "malformed_event_rows": event_malformed,
            "warnings": event_warnings,
            "newest_run_at": _isoformat(newest),
            "scan_lag_seconds": int((now - newest).total_seconds()) if newest is not None else None,
        },
    }


def _format_value(value: object, suffix: str = "") -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        text = f"{value:.3f}".rstrip("0").rstrip(".")
    else:
        text = str(value)
    return html.escape(text + suffix)


def _html_table(headers: list[str], rows: list[list[object]], empty: str) -> str:
    if not rows:
        colspan = len(headers)
        return (
            "<table><thead><tr>"
            + "".join(f"<th>{html.escape(header)}</th>" for header in headers)
            + f"</tr></thead><tbody><tr><td colspan=\"{colspan}\">{html.escape(empty)}</td></tr></tbody></table>"
        )
    body = []
    for row in rows:
        body.append("<tr>" + "".join(f"<td>{_format_value(value)}</td>" for value in row) + "</tr>")
    return (
        "<table><thead><tr>"
        + "".join(f"<th>{html.escape(header)}</th>" for header in headers)
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
    )


def render_dashboard_html(summary: dict[str, Any]) -> str:
    herd_rows = [
        [
            row["event"],
            row["events"],
            row["p50_procs_per_event"],
            row["p90_procs_per_event"],
            row["p50_cpu_seconds_per_event"],
            row["p90_cpu_seconds_per_event"],
            f"{row['event_uid_groups']} uid / {row['window_groups']} window",
        ]
        for row in summary["herd"]["event_types"]
    ]
    latency_event_rows = [
        [row["name"], row["runs"], row["p50_ms"], row["p90_ms"]]
        for row in summary["latency"]["event_types"]
    ]
    latency_hook_rows = [
        [row["name"], row["runs"], row["p50_ms"], row["p90_ms"]]
        for row in summary["latency"]["hooks"]
    ]
    daily_rows = [
        [row["date"], row["spoke"], row["silent"], row["blocked"], row["crashed"], row["caught_error"], row["timed_out"]]
        for row in summary["health"]["daily_outcome_mix"]
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
        for row in summary["health"]["hooks"]
    ]
    ledger = summary["ledger"]
    empty_message = "No runner metrics rows found."
    style = """
body{font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;background:#f7f8f5;color:#18201a}
main{max-width:1180px;margin:0 auto;padding:32px 24px 48px}
h1{font-size:32px;margin:0 0 6px} h2{font-size:21px;margin:28px 0 10px}
.meta{color:#58645b;margin:0 0 20px}.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px;margin:16px 0}
.stat{border:1px solid #d9ded6;background:#fff;border-radius:6px;padding:12px}.stat strong{display:block;font-size:24px}
table{width:100%;border-collapse:collapse;background:#fff;border:1px solid #d9ded6;margin:10px 0 18px}
th,td{padding:8px 10px;border-bottom:1px solid #e8ebe6;text-align:left;font-size:14px}th{background:#edf1ec;font-weight:650}
section{margin-top:24px}.empty{padding:18px;border:1px solid #d9ded6;background:#fff;border-radius:6px}
"""
    empty = f"<p class=\"empty\">{empty_message}</p>" if ledger["run_rows"] == 0 else ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hook Runner Dashboard</title>
<style>{style}</style>
</head>
<body>
<main>
<h1>Hook Runner Dashboard</h1>
<p class="meta">Folded at {_format_value(summary['generated_at'])} from summary.json.</p>
{empty}
<section>
<h2>Herd</h2>
{_html_table(['Event type','Events','p50 procs/event','p90 procs/event','p50 CPU-s/event','p90 CPU-s/event','Grouping'], herd_rows, empty_message)}
</section>
<section>
<h2>Latency</h2>
{_html_table(['Event type','Runs','p50 ms','p90 ms'], latency_event_rows, empty_message)}
{_html_table(['Hook','Runs','p50 ms','p90 ms'], latency_hook_rows, empty_message)}
</section>
<section>
<h2>Health</h2>
<div class="stats">
<div class="stat"><span>Runs</span><strong>{_format_value(summary['health']['rates']['runs'])}</strong></div>
<div class="stat"><span>Timeout rate</span><strong>{_format_value(summary['health']['rates']['timeout_rate'])}</strong></div>
<div class="stat"><span>Crash rate</span><strong>{_format_value(summary['health']['rates']['crash_rate'])}</strong></div>
</div>
{_html_table(['Date','Spoke','Silent','Blocked','Crashed','Caught error','Timed out'], daily_rows, empty_message)}
{_html_table(['Hook','Runs','Spoke','Silent','Blocked','Crashed','Caught error','Timed out','p95 ms','Last error'], hook_rows, empty_message)}
</section>
<section>
<h2>Ledger</h2>
{_html_table(['Metric','Value'], [
    ['runs.jsonl exists', ledger['runs_jsonl_exists']],
    ['runs.jsonl size bytes', ledger['runs_jsonl_size_bytes']],
    ['run rows', ledger['run_rows']],
    ['malformed run rows', ledger['malformed_run_rows']],
    ['event files', ledger['event_files']],
    ['event rows', ledger['event_rows']],
    ['malformed event rows', ledger['malformed_event_rows']],
    ['newest run at', ledger['newest_run_at']],
    ['scan lag seconds', ledger['scan_lag_seconds']],
], 'No ledger data.')}
</section>
</main>
</body>
</html>
"""


def _write_artifact(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_dashboard(root: Path, since: timedelta, now: datetime) -> tuple[Path, Path, dict[str, Any]]:
    threshold = now - since
    rows, run_malformed, run_error = _dashboard_read_rows(root / "runs.jsonl", threshold)
    if run_error is not None:
        raise RuntimeError(run_error)
    event_rows, event_malformed, event_warnings = _dashboard_read_event_rows(root, threshold)
    registered, config_warnings = read_registered()
    summary = build_dashboard_summary(
        rows,
        run_malformed,
        event_rows,
        event_malformed,
        event_warnings,
        registered,
        config_warnings,
        root,
        now,
    )
    summary_path = root / "summary.json"
    html_path = root / "dashboard.html"
    _write_artifact(summary_path, json.dumps(summary, indent=2, sort_keys=True) + "\n")
    rendered_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    _write_artifact(html_path, render_dashboard_html(rendered_summary))
    return summary_path, html_path, rendered_summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", default="7d")
    parser.add_argument("--days", type=float)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--html", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--events", action="store_true", default=True)
    mode.add_argument("--runs", action="store_true")
    mode.add_argument("--judge", action="store_true")
    mode.add_argument("--skills", action="store_true")
    mode.add_argument("--harness-gap", action="store_true")
    mode.add_argument("--scorecard", action="store_true")
    parser.add_argument("--grace", default="1h")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        since = timedelta(days=args.days) if args.days is not None else parse_since(args.since)
        grace = parse_since(args.grace)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.days is not None and args.days <= 0:
        print("--days must be positive", file=sys.stderr)
        return 2
    if args.scorecard:
        rows, malformed, error = read_rows(metrics_path(), datetime.now(timezone.utc) - since)
        if error is not None:
            print(error)
            return 2
        report = build_scorecard(rows or [], malformed, [])
        if args.json:
            print(json.dumps(report, sort_keys=True))
        else:
            print(format_scorecard_table(report), end="")
        return 0
    if args.html:
        try:
            summary_path, html_path, summary = write_dashboard(metrics_dir(), since, datetime.now(timezone.utc))
        except RuntimeError as exc:
            print(f"dashboard fold error: {exc}", file=sys.stderr)
            return 2
        except OSError as exc:
            print(f"dashboard write error: {exc}", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(summary, sort_keys=True))
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
