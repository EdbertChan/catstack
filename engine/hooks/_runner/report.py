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

SDK_DIR = Path(__file__).resolve().parents[1] / "_sdk"
sys.path.insert(0, str(SDK_DIR))

import registry

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skill-usage-log"))

import detect as skill_detect

FAILURE_OUTCOMES = {"crashed", "timed_out", "caught_error"}
OUTCOMES = ("spoke", "silent", "blocked", "crashed", "caught_error", "timed_out")


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
