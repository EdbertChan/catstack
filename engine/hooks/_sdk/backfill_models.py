"""Fill blank hook-event models from the session log on each machine.

New events already do this when they are recorded. This command sends a
second copy of each past event that still has a blank or synthetic model,
using the same time, so charts that skip blanks show the real model.

Sources:
- Codex: rollout session log
- Claude: project transcript
- Cursor: local metrics rows that already named a model for the same session

Copies are keyed by the original event id. A second run skips ids already
copied. Events with no matching session log stay blank.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator
from urllib import error, request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from transcripts import (  # noqa: E402
    SYNTHETIC,
    claude_model_points,
    claude_projects_root,
    codex_model_points,
    codex_sessions_root,
    is_publishable_model,
)

EVENT_NAME = "catstack_hook_event"
MODEL_SOURCE = "session-model"
INSERT_NS = uuid.UUID("b3c1d8e2-4a70-4f15-9c2d-6e8f0a1b2c3d")
QUERY_KEY_ENV = "CATSTACK_POSTHOG_QUERY_KEY"
PROJECT_ENV = "CATSTACK_POSTHOG_PROJECT_ID"
QUERY_HOST_ENV = "CATSTACK_POSTHOG_QUERY_HOST"
DEFAULT_QUERY_HOST = "https://us.posthog.com"
DEFAULT_PROJECT = "489684"
WINDOW_SECONDS = 3
PAGE = 5000
SESSION_CHUNK = 200
HARNESSES = ("claude", "codex", "cursor")
SESSION_ID_RE = re.compile(r"^[0-9A-Za-z-]{8,64}$")
METRICS_DIR_ENV = "CATSTACK_HOOK_METRICS_DIR"
DEFAULT_METRICS_DIR = Path.home() / ".cache" / "catstack-hook-metrics"
PUBLISH_FIELDS = (
    "hook",
    "harness",
    "rule_id",
    "action",
    "mode",
    "machine",
    "session_id",
    "model",
    "skill",
    "duration_ms",
    "ts",
    "model_source",
    "source_uuid",
)


def model_as_of(points: list[tuple[str, str]], stamp: str) -> str:
    """Latest model at or before stamp. The earliest model when stamp is earlier."""
    if not points:
        return ""
    when = _parse_time(stamp)
    chosen = ""
    for point_stamp, model in points:
        point_when = _parse_time(point_stamp)
        if when is None or point_when is None or point_when <= when:
            chosen = model
        elif chosen:
            break
    return chosen or points[0][1]


def recover_session(
    machine: str,
    hook: str,
    stamp: str,
    peers: dict[tuple[str, str], list[tuple[str, str]]],
) -> str:
    """Session id shared by nearby events for this hook, else for this machine."""
    found = _unique_near(peers.get((machine, hook), []), stamp)
    if found:
        return found
    same_machine: list[tuple[str, str]] = []
    for (peer_machine, _hook), rows in peers.items():
        if peer_machine == machine:
            same_machine.extend(rows)
    return _unique_near(same_machine, stamp)


def index_codex_rollouts(root: Path) -> dict[str, list[tuple[str, str]]]:
    index: dict[str, list[tuple[str, str]]] = {}
    if not root.is_dir():
        return index
    for path in sorted(root.glob("*/*/*/rollout-*.jsonl")):
        session_id, points = codex_model_points(str(path))
        if not session_id or not points:
            continue
        index.setdefault(session_id, []).extend(points)
    for session_id in index:
        index[session_id].sort()
    return index


def index_claude_transcripts(root: Path) -> dict[str, list[tuple[str, str]]]:
    index: dict[str, list[tuple[str, str]]] = {}
    if not root.is_dir():
        return index
    for path in sorted(root.glob("*/*.jsonl")):
        name = path.name
        if name.startswith("agent-"):
            continue
        session_id, points = claude_model_points(str(path))
        if not session_id or not points:
            continue
        real = [(stamp, model) for stamp, model in points if is_publishable_model(model)]
        if not real:
            continue
        index.setdefault(session_id, []).extend(real)
    for session_id in index:
        index[session_id].sort(key=lambda row: row[0])
    return index


def index_local_metrics(root: Path) -> dict[str, dict[str, list[tuple[str, str]]]]:
    """Models already recorded on local metrics rows, keyed by harness then session."""
    index: dict[str, dict[str, list[tuple[str, str]]]] = {}
    if not root.is_dir():
        return index
    for path in sorted(root.glob("events-*.jsonl")):
        try:
            handle = open(path, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                harness = row.get("harness")
                session_id = row.get("session_id")
                model = row.get("model")
                stamp = row.get("ts") or ""
                if harness not in HARNESSES:
                    continue
                if not isinstance(session_id, str) or not SESSION_ID_RE.match(session_id):
                    continue
                if not isinstance(model, str) or not is_publishable_model(model):
                    continue
                if not isinstance(stamp, str) or not stamp:
                    continue
                index.setdefault(harness, {}).setdefault(session_id, []).append((stamp, model.strip()))
    for harness_rows in index.values():
        for session_id in harness_rows:
            harness_rows[session_id].sort(key=lambda row: row[0])
    return index


def plan_copies(
    events: Iterable[dict[str, str]],
    timelines: dict[str, list[tuple[str, str]]],
    peers: dict[tuple[str, str], list[tuple[str, str]]],
    already: set[str],
) -> tuple[list[dict[str, object]], int]:
    copies: list[dict[str, object]] = []
    unmatched = 0
    for event in events:
        source = event.get("uuid") or ""
        if not source or source in already:
            continue
        session_id = event.get("session_id") or ""
        if not session_id:
            session_id = recover_session(
                event.get("machine") or "",
                event.get("hook") or "",
                event.get("timestamp") or "",
                peers,
            )
        model = model_as_of(timelines.get(session_id, []), event.get("timestamp") or "")
        if not model:
            unmatched += 1
            continue
        copies.append(_copy(event, session_id, model))
    return copies, unmatched


def peer_index(events: Iterable[dict[str, str]]) -> dict[tuple[str, str], list[tuple[str, str]]]:
    peers: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for event in events:
        session_id = event.get("session_id") or ""
        if not session_id:
            continue
        key = (event.get("machine") or "", event.get("hook") or "")
        peers.setdefault(key, []).append((event.get("timestamp") or "", session_id))
    return peers


def _copy(event: dict[str, str], session_id: str, model: str) -> dict[str, object]:
    source = event["uuid"]
    stamp = event.get("timestamp") or event.get("ts") or ""
    harness = event.get("harness") or ""
    return {
        "hook": event.get("hook") or "",
        "harness": harness,
        "rule_id": event.get("rule_id") or "",
        "action": event.get("action") or "",
        "mode": event.get("mode") or "",
        "machine": event.get("machine") or "",
        "session_id": session_id,
        "model": model,
        "skill": event.get("skill") or "",
        "duration_ms": event.get("duration_ms") or 0,
        "ts": event.get("ts") or stamp,
        "model_source": MODEL_SOURCE,
        "source_uuid": source,
        "finding_id": str(uuid.uuid5(INSERT_NS, f"{MODEL_SOURCE}|{source}")),
        "capture_timestamp": stamp,
    }


def _unique_near(rows: list[tuple[str, str]], stamp: str) -> str:
    when = _parse_time(stamp)
    if when is None:
        return ""
    found: set[str] = set()
    for peer_stamp, session_id in rows:
        peer_when = _parse_time(peer_stamp)
        if peer_when is None:
            continue
        if abs((peer_when - when).total_seconds()) <= WINDOW_SECONDS:
            found.add(session_id)
    if len(found) == 1:
        return next(iter(found))
    return ""


def _parse_time(stamp: str) -> datetime | None:
    text = stamp.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def emit_local_models() -> Iterator[dict[str, str]]:
    for session_id, points in index_codex_rollouts(Path(codex_sessions_root())).items():
        for stamp, model in points:
            yield {"harness": "codex", "session_id": session_id, "ts": stamp, "model": model}
    for session_id, points in index_claude_transcripts(Path(claude_projects_root())).items():
        for stamp, model in points:
            yield {"harness": "claude", "session_id": session_id, "ts": stamp, "model": model}
    metrics_root = Path(os.environ.get(METRICS_DIR_ENV, str(DEFAULT_METRICS_DIR)))
    for harness, sessions in index_local_metrics(metrics_root).items():
        for session_id, points in sessions.items():
            for stamp, model in points:
                yield {"harness": harness, "session_id": session_id, "ts": stamp, "model": model}


def merge_timelines(rows: Iterable[dict[str, str]]) -> dict[str, list[tuple[str, str]]]:
    timelines: dict[str, list[tuple[str, str]]] = {}
    for row in rows:
        session_id = row.get("session_id") or ""
        stamp = row.get("ts") or ""
        model = row.get("model") or ""
        if session_id and model and model != SYNTHETIC:
            timelines.setdefault(session_id, []).append((stamp, model))
    for session_id in timelines:
        timelines[session_id].sort(key=lambda row: row[0])
    return timelines


def sessions_by_harness(rows: Iterable[dict[str, str]]) -> dict[str, list[str]]:
    grouped: dict[str, set[str]] = {name: set() for name in HARNESSES}
    for row in rows:
        harness = row.get("harness") or ""
        session_id = row.get("session_id") or ""
        model = row.get("model") or ""
        if harness in grouped and session_id and SESSION_ID_RE.match(session_id) and model and model != SYNTHETIC:
            grouped[harness].add(session_id)
    return {harness: sorted(ids) for harness, ids in grouped.items()}


def _cursor_clause(after: tuple[str, str] | None) -> str:
    """Keyset page. Personal query keys reject OFFSET."""
    if after is None:
        return ""
    stamp, event_id = after
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?", stamp):
        raise ValueError("bad cursor timestamp")
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", event_id):
        raise ValueError("bad cursor uuid")
    return (
        "AND (toString(timestamp) > '{stamp}' "
        "OR (toString(timestamp) = '{stamp}' AND toString(uuid) > '{event_id}'))"
    ).format(stamp=stamp, event_id=event_id)


def _session_in_clause(session_ids: list[str]) -> str:
    cleaned: list[str] = []
    for session_id in session_ids:
        if not SESSION_ID_RE.match(session_id):
            raise ValueError(f"bad session id: {session_id!r}")
        cleaned.append(f"'{session_id}'")
    return ", ".join(cleaned)


def blank_query(harness: str, session_ids: list[str], after: tuple[str, str] | None) -> str:
    if harness not in HARNESSES:
        raise ValueError(f"bad harness: {harness}")
    return f"""
SELECT
  toString(uuid) AS uuid,
  toString(timestamp) AS timestamp,
  properties.hook AS hook,
  properties.harness AS harness,
  properties.rule_id AS rule_id,
  properties.action AS action,
  properties.mode AS mode,
  properties.machine AS machine,
  properties.session_id AS session_id,
  properties.skill AS skill,
  toString(properties.duration_ms) AS duration_ms,
  properties.ts AS ts
FROM events
WHERE event = '{EVENT_NAME}'
  AND properties.harness = '{harness}'
  AND properties.session_id IN ({_session_in_clause(session_ids)})
  AND (
    properties.model = '' OR properties.model IS NULL OR properties.model = '{SYNTHETIC}'
  )
  {_cursor_clause(after)}
ORDER BY timestamp, toString(uuid)
LIMIT {PAGE}
"""


def copied_query(after: tuple[str, str] | None) -> str:
    return f"""
SELECT
  toString(uuid) AS uuid,
  toString(timestamp) AS timestamp,
  properties.source_uuid AS source_uuid
FROM events
WHERE event = '{EVENT_NAME}'
  AND properties.model_source IN ('{MODEL_SOURCE}', 'codex-session')
  AND properties.source_uuid != ''
  {_cursor_clause(after)}
ORDER BY timestamp, toString(uuid)
LIMIT {PAGE}
"""


def filled_peer_query(harness: str, after: tuple[str, str] | None) -> str:
    if harness not in HARNESSES:
        raise ValueError(f"bad harness: {harness}")
    return f"""
SELECT
  toString(uuid) AS uuid,
  toString(timestamp) AS timestamp,
  properties.session_id AS session_id,
  properties.model AS model
FROM events
WHERE event = '{EVENT_NAME}'
  AND properties.harness = '{harness}'
  AND properties.session_id != ''
  AND properties.model != ''
  AND properties.model IS NOT NULL
  AND properties.model != '{SYNTHETIC}'
  {_cursor_clause(after)}
ORDER BY timestamp, toString(uuid)
LIMIT {PAGE}
"""


def query_rows(query_key: str, project: str, host: str, hogql: str) -> list[list[object]]:
    body = json.dumps({"query": {"kind": "HogQLQuery", "query": hogql}}).encode()
    req = request.Request(
        f"{host.rstrip('/')}/api/projects/{project}/query/",
        data=body,
        headers={"Authorization": f"Bearer {query_key}", "Content-Type": "application/json"},
    )
    payload = None
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            with request.urlopen(req, timeout=120) as resp:
                payload = json.loads(resp.read().decode())
            break
        except error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:500]
            if exc.code in {429, 500, 502, 503, 504} and attempt < 3:
                last_error = RuntimeError(f"posthog query {exc.code}: {detail}")
                time.sleep(5 * (attempt + 1))
                continue
            raise RuntimeError(f"posthog query {exc.code}: {detail}") from exc
        except (error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            last_error = exc
            time.sleep(2 * (attempt + 1))
    if payload is None:
        raise RuntimeError(f"posthog query failed: {last_error}") from last_error
    if payload.get("error"):
        raise RuntimeError(str(payload["error"]))
    results = payload.get("results")
    return results if isinstance(results, list) else []


def fetch_all(query_key: str, project: str, host: str, sql_for_cursor) -> list[list[object]]:
    rows: list[list[object]] = []
    after: tuple[str, str] | None = None
    while True:
        page = query_rows(query_key, project, host, sql_for_cursor(after))
        if not page:
            break
        rows.extend(page)
        if len(page) < PAGE:
            break
        last = page[-1]
        if not isinstance(last, list) or len(last) < 2:
            break
        cursor = (str(last[1]), str(last[0]))
        if cursor == after:
            break
        after = cursor
    return rows


def blank_session_ids_query(harness: str, after: tuple[str, str] | None) -> str:
    if harness not in HARNESSES:
        raise ValueError(f"bad harness: {harness}")
    if after is None:
        cursor = ""
    else:
        session_id, _event_id = after
        if not SESSION_ID_RE.match(session_id):
            raise ValueError("bad session id cursor")
        cursor = f"AND properties.session_id > '{session_id}'"
    return f"""
SELECT
  properties.session_id AS session_id,
  properties.session_id AS session_id_dup
FROM events
WHERE event = '{EVENT_NAME}'
  AND properties.harness = '{harness}'
  AND properties.session_id != ''
  AND properties.session_id IS NOT NULL
  AND (
    properties.model = '' OR properties.model IS NULL OR properties.model = '{SYNTHETIC}'
  )
  {cursor}
GROUP BY properties.session_id
ORDER BY properties.session_id
LIMIT {PAGE}
"""


def fetch_blank_session_ids(query_key: str, project: str, host: str, harness: str) -> list[str]:
    rows = fetch_all(query_key, project, host, lambda after: blank_session_ids_query(harness, after))
    found: list[str] = []
    for row in rows:
        if not isinstance(row, list) or not row:
            continue
        session_id = str(row[0] or "")
        if SESSION_ID_RE.match(session_id):
            found.append(session_id)
    return found


def fetch_blanks_for_sessions(
    query_key: str,
    project: str,
    host: str,
    harness: str,
    session_ids: list[str],
) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    for start in range(0, len(session_ids), SESSION_CHUNK):
        chunk = session_ids[start : start + SESSION_CHUNK]

        def sql_for_cursor(after: tuple[str, str] | None, _chunk: list[str] = chunk) -> str:
            return blank_query(harness, _chunk, after)

        events.extend(events_from_results(fetch_all(query_key, project, host, sql_for_cursor)))
        print(
            f"backfill-models: {harness} blank pages for sessions {start + len(chunk)}/{len(session_ids)}",
            file=sys.stderr,
        )
    return events


def enrich_timelines_from_posthog(
    query_key: str,
    project: str,
    host: str,
    harness: str,
    timelines: dict[str, list[tuple[str, str]]],
) -> set[str]:
    rows = fetch_all(query_key, project, host, lambda after: filled_peer_query(harness, after))
    touched: set[str] = set()
    for row in rows:
        if not isinstance(row, list) or len(row) < 4:
            continue
        session_id, stamp, model = str(row[2] or ""), str(row[1] or ""), str(row[3] or "")
        if not SESSION_ID_RE.match(session_id) or not model or model == SYNTHETIC:
            continue
        timelines.setdefault(session_id, []).append((stamp, model))
        touched.add(session_id)
    for session_id in touched:
        timelines[session_id].sort(key=lambda item: item[0])
    return touched


def events_from_results(results: list[list[object]]) -> list[dict[str, str]]:
    keys = (
        "uuid",
        "timestamp",
        "hook",
        "harness",
        "rule_id",
        "action",
        "mode",
        "machine",
        "session_id",
        "skill",
        "duration_ms",
        "ts",
    )
    events: list[dict[str, str]] = []
    for row in results:
        if not isinstance(row, list):
            continue
        event = {key: "" if value is None else str(value) for key, value in zip(keys, row)}
        events.append(event)
    return events


def capture_body(api_key: str, row: dict[str, object]) -> dict[str, object]:
    properties = {key: row.get(key, "") for key in PUBLISH_FIELDS}
    properties["$geoip_disable"] = True
    properties["$insert_id"] = str(row.get("finding_id") or "")
    return {
        "api_key": api_key,
        "event": EVENT_NAME,
        "distinct_id": str(row.get("session_id") or row.get("machine") or "catstack"),
        "properties": properties,
        "timestamp": str(row.get("capture_timestamp") or row.get("ts") or ""),
        "uuid": str(row.get("finding_id") or ""),
    }


def post_batch(host: str, batch: list[dict[str, object]]) -> None:
    body = {
        "api_key": batch[0]["api_key"],
        "historical_migration": True,
        "batch": [
            {
                "event": item["event"],
                "distinct_id": item["distinct_id"],
                "properties": item["properties"],
                "timestamp": item["timestamp"],
                "uuid": item["uuid"],
            }
            for item in batch
        ],
    }
    data = gzip.compress(json.dumps(body).encode("utf-8"))
    req = request.Request(
        f"{host.rstrip('/')}/batch/",
        data=data,
        headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
        method="POST",
    )
    with request.urlopen(req, timeout=60) as resp:
        resp.read()


def publish(rows: list[dict[str, object]]) -> tuple[int, int]:
    api_key = _capture_key()
    if not api_key:
        raise SystemExit("CATSTACK_POSTHOG_API_KEY is not set")
    host = _capture_host()
    payloads = [capture_body(api_key, row) for row in rows]
    sent = 0
    failed = 0
    for start in range(0, len(payloads), 200):
        batch = payloads[start : start + 200]
        sent_batch = False
        last_error: Exception | None = None
        for attempt in range(4):
            try:
                post_batch(host, batch)
                sent_batch = True
                break
            except (error.URLError, TimeoutError, ConnectionError, OSError, ValueError) as exc:
                last_error = exc
                time.sleep(2 * (attempt + 1))
        if sent_batch:
            sent += len(batch)
            print(f"backfill-models: sent {sent}/{len(payloads)}", file=sys.stderr)
        else:
            failed += len(batch)
            print(f"backfill-models: batch failed: {last_error}", file=sys.stderr)
    return sent, failed


def remote_model_rows(target: object, connect_timeout: int) -> list[dict[str, str]]:
    import subprocess

    host = getattr(target, "host")
    user = getattr(target, "user")
    remote_dir = f"/tmp/catstack-backfill-models-{os.getpid()}"
    files = [
        Path(__file__).resolve(),
        Path(__file__).resolve().with_name("transcripts.py"),
    ]
    ssh_base = ["-o", "BatchMode=yes", "-o", f"ConnectTimeout={connect_timeout}", f"{user}@{host}"]
    subprocess.run(["ssh", *ssh_base, f"mkdir -p {remote_dir}"], check=True, capture_output=True, text=True)
    subprocess.run(
        [
            "scp",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={connect_timeout}",
            *[str(path) for path in files],
            f"{user}@{host}:{remote_dir}/",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    remote = [
        "ssh",
        *ssh_base,
        (
            f"PYTHONPATH={remote_dir} python3 {remote_dir}/backfill_models.py --emit-models; "
            f"status=$?; rm -rf {remote_dir}; exit $status"
        ),
    ]
    result = subprocess.run(remote, check=False, capture_output=True, text=True)
    rows: list[dict[str, str]] = []
    for line in (result.stdout or "").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(
                {
                    key: str(row.get(key) or "")
                    for key in ("harness", "session_id", "ts", "model")
                }
            )
    if result.returncode != 0 and not rows:
        detail = (result.stderr or "").strip()
        raise RuntimeError(detail or f"remote model scan exit {result.returncode}")
    return rows


def _import_flags():
    flags_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_flags")
    if flags_dir not in sys.path:
        sys.path.insert(0, flags_dir)
    import flags

    return flags


def _capture_key() -> str:
    found = _import_flags().resolve_flag("CATSTACK_POSTHOG_API_KEY", os.environ, None)
    return (found.value or "").strip()


def _capture_host() -> str:
    found = _import_flags().resolve_flag("CATSTACK_POSTHOG_HOST", os.environ, None)
    return ((found.value or "").strip() or "https://us.i.posthog.com").rstrip("/")


def _query_key() -> str:
    return os.environ.get(QUERY_KEY_ENV, "").strip()


def _scan_model_rows(args: argparse.Namespace) -> list[dict[str, str]]:
    print("backfill-models: scanning local sessions", file=sys.stderr)
    model_rows = list(emit_local_models())
    print(f"backfill-models: local lines {len(model_rows)}", file=sys.stderr)
    if args.skip_remote:
        return model_rows
    try:
        flags_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_flags")
        if flags_dir not in sys.path:
            sys.path.insert(0, flags_dir)
        import collect

        targets = collect.load_targets(Path(args.config))
    except (OSError, ValueError, ImportError) as exc:
        print(f"catstack-hook-error backfill-models: no fleet config: {exc}", file=sys.stderr)
        targets = []
    for target in targets:
        if not target.host or not target.user:
            continue
        print(f"backfill-models: scanning {target.target_id}", file=sys.stderr)
        try:
            found = remote_model_rows(target, args.connect_timeout)
            print(f"backfill-models: {target.target_id} sessions lines {len(found)}", file=sys.stderr)
            model_rows.extend(found)
        except Exception as exc:
            print(
                f"catstack-hook-error backfill-models: {target.target_id}: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
    return model_rows


def _scan_timelines(args: argparse.Namespace) -> dict[str, list[tuple[str, str]]]:
    return merge_timelines(_scan_model_rows(args))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit-models", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--config", default=str(Path.home() / ".invoker" / "config.json"))
    parser.add_argument("--connect-timeout", type=int, default=10)
    parser.add_argument("--skip-remote", action="store_true")
    parser.add_argument("--timeline-cache", default="")
    parser.add_argument("--from-timeline-cache", default="")
    parser.add_argument(
        "--harness",
        action="append",
        choices=HARNESSES,
        dest="harnesses",
        help="Limit to one harness; repeat for several. Default: all.",
    )
    parser.add_argument(
        "--enrich-posthog-peers",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Learn models from PostHog rows that already have a model (default: on).",
    )
    args = parser.parse_args(argv)
    harnesses = tuple(args.harnesses) if args.harnesses else HARNESSES

    if args.emit_models:
        for row in emit_local_models():
            print(json.dumps(row, sort_keys=True))
        return 0

    query_key = _query_key()
    if not query_key:
        raise SystemExit(f"{QUERY_KEY_ENV} is not set")
    project = os.environ.get(PROJECT_ENV, DEFAULT_PROJECT).strip() or DEFAULT_PROJECT
    query_host = os.environ.get(QUERY_HOST_ENV, DEFAULT_QUERY_HOST).strip() or DEFAULT_QUERY_HOST

    if args.from_timeline_cache:
        print(f"backfill-models: reading {args.from_timeline_cache}", file=sys.stderr)
        loaded = json.loads(Path(args.from_timeline_cache).read_text(encoding="utf-8"))
        timelines = {
            session_id: [(str(stamp), str(model)) for stamp, model in points]
            for session_id, points in loaded.get("timelines", loaded).items()
        }
        harness_sessions = {
            harness: list(ids)
            for harness, ids in (loaded.get("harness_sessions") or {}).items()
            if harness in HARNESSES
        }
        if not harness_sessions:
            harness_sessions = {harness: sorted(timelines) for harness in harnesses}
        model_rows = []
    else:
        model_rows = _scan_model_rows(args)
        timelines = merge_timelines(model_rows)
        harness_sessions = sessions_by_harness(model_rows)
        if args.timeline_cache:
            Path(args.timeline_cache).write_text(
                json.dumps(
                    {"timelines": timelines, "harness_sessions": harness_sessions},
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            print(f"backfill-models: wrote {args.timeline_cache}", file=sys.stderr)

    if args.enrich_posthog_peers:
        for harness in harnesses:
            print(f"backfill-models: enriching {harness} from PostHog peers", file=sys.stderr)
            try:
                touched = enrich_timelines_from_posthog(query_key, project, query_host, harness, timelines)
            except Exception as exc:
                print(
                    f"catstack-hook-error backfill-models: enrich {harness}: {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
                continue
            harness_sessions[harness] = sorted(set(harness_sessions.get(harness, [])) | touched)

    blank: list[dict[str, str]] = []
    for harness in harnesses:
        known = {sid for sid in harness_sessions.get(harness, []) if SESSION_ID_RE.match(sid)}
        print(f"backfill-models: {harness} local sessions {len(known)}", file=sys.stderr)
        if not known:
            continue
        print(f"backfill-models: {harness} listing blank PostHog sessions", file=sys.stderr)
        try:
            blank_sessions = fetch_blank_session_ids(query_key, project, query_host, harness)
        except Exception as exc:
            print(
                f"catstack-hook-error backfill-models: list {harness}: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            continue
        session_ids = sorted(known & set(blank_sessions))
        print(
            f"backfill-models: {harness} fillable sessions {len(session_ids)} "
            f"(posthog blanks {len(blank_sessions)})",
            file=sys.stderr,
        )
        if not session_ids:
            continue
        blank.extend(fetch_blanks_for_sessions(query_key, project, query_host, harness, session_ids))

    copied = {
        str(row[2])
        for row in fetch_all(query_key, project, query_host, copied_query)
        if isinstance(row, list) and len(row) > 2 and row[2]
    }
    copies, unmatched = plan_copies(blank, timelines, peer_index(blank), copied)
    if args.dry_run:
        sent, failed = len(copies), 0
    else:
        sent, failed = publish(copies)
    by_harness: dict[str, int] = {}
    for row in copies:
        harness = str(row.get("harness") or "")
        by_harness[harness] = by_harness.get(harness, 0) + 1
    print(
        json.dumps(
            {
                "blank": len(blank),
                "already_copied": len(copied),
                "sessions": len(timelines),
                "queued": len(copies),
                "queued_by_harness": by_harness,
                "unmatched": unmatched,
                "sent_ok": sent,
                "failed": failed,
                "dry_run": args.dry_run,
                "harnesses": list(harnesses),
            },
            sort_keys=True,
        )
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
