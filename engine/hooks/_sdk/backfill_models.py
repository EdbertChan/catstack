"""Fill Codex hook events with the model named in the session log.

New events already do this when they are recorded. This command sends a
second copy of each past Codex event that still has a blank model, using
the same time, so charts that skip blank models show sol, terra, and luna.

Copies are keyed by the original event id. A second run skips ids already
copied. Events with no session log stay blank.
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

from transcripts import codex_model_points, codex_sessions_root  # noqa: E402

EVENT_NAME = "catstack_hook_event"
MODEL_SOURCE = "codex-session"
INSERT_NS = uuid.UUID("b3c1d8e2-4a70-4f15-9c2d-6e8f0a1b2c3d")
QUERY_KEY_ENV = "CATSTACK_POSTHOG_QUERY_KEY"
PROJECT_ENV = "CATSTACK_POSTHOG_PROJECT_ID"
QUERY_HOST_ENV = "CATSTACK_POSTHOG_QUERY_HOST"
DEFAULT_QUERY_HOST = "https://us.posthog.com"
DEFAULT_PROJECT = "489684"
WINDOW_SECONDS = 3
PAGE = 5000
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


def index_rollouts(root: Path) -> dict[str, list[tuple[str, str]]]:
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
    return {
        "hook": event.get("hook") or "",
        "harness": event.get("harness") or "codex",
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
        "finding_id": str(uuid.uuid5(INSERT_NS, f"codex-model|{source}")),
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
    root = Path(codex_sessions_root())
    index = index_rollouts(root)
    for session_id, points in index.items():
        for stamp, model in points:
            yield {"session_id": session_id, "ts": stamp, "model": model}


def merge_timelines(rows: Iterable[dict[str, str]]) -> dict[str, list[tuple[str, str]]]:
    timelines: dict[str, list[tuple[str, str]]] = {}
    for row in rows:
        session_id = row.get("session_id") or ""
        stamp = row.get("ts") or ""
        model = row.get("model") or ""
        if session_id and stamp and model:
            timelines.setdefault(session_id, []).append((stamp, model))
    for session_id in timelines:
        timelines[session_id].sort()
    return timelines


def _cursor_clause(after: tuple[str, str] | None) -> str:
    """Keyset page. Personal query keys reject OFFSET."""
    if after is None:
        return ""
    stamp, event_id = after
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?", stamp):
        raise ValueError("bad cursor timestamp")
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", event_id):
        raise ValueError("bad cursor uuid")
    # HogQL exposes timestamp as text here, so both sides stay strings.
    return (
        "AND (toString(timestamp) > '{stamp}' "
        "OR (toString(timestamp) = '{stamp}' AND toString(uuid) > '{event_id}'))"
    ).format(stamp=stamp, event_id=event_id)


def blank_codex_query(after: tuple[str, str] | None) -> str:
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
  AND properties.harness = 'codex'
  AND (properties.model = '' OR properties.model IS NULL)
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
  AND properties.model_source = '{MODEL_SOURCE}'
  AND properties.source_uuid != ''
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
    files = [Path(__file__).resolve(), Path(__file__).resolve().with_name("transcripts.py")]
    ssh_base = ["-o", "BatchMode=yes", "-o", f"ConnectTimeout={connect_timeout}", f"{user}@{host}"]
    subprocess.run(["ssh", *ssh_base, f"mkdir -p {remote_dir}"], check=True, capture_output=True, text=True)
    subprocess.run(
        ["scp", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={connect_timeout}", *[str(path) for path in files], f"{user}@{host}:{remote_dir}/"],
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
            rows.append({key: str(row.get(key) or "") for key in ("session_id", "ts", "model")})
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


def _scan_timelines(args: argparse.Namespace) -> dict[str, list[tuple[str, str]]]:
    print("backfill-models: scanning local sessions", file=sys.stderr)
    model_rows = list(emit_local_models())
    print(f"backfill-models: local lines {len(model_rows)}", file=sys.stderr)
    if args.skip_remote:
        return merge_timelines(model_rows)
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
    return merge_timelines(model_rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit-models", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--config", default=str(Path.home() / ".invoker" / "config.json"))
    parser.add_argument("--connect-timeout", type=int, default=10)
    parser.add_argument("--skip-remote", action="store_true")
    parser.add_argument("--timeline-cache", default="")
    parser.add_argument("--from-timeline-cache", default="")
    args = parser.parse_args(argv)

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
            for session_id, points in loaded.items()
        }
    else:
        timelines = _scan_timelines(args)
        if args.timeline_cache:
            Path(args.timeline_cache).write_text(
                json.dumps(timelines, sort_keys=True),
                encoding="utf-8",
            )
            print(f"backfill-models: wrote {args.timeline_cache}", file=sys.stderr)

    blank = events_from_results(fetch_all(query_key, project, query_host, blank_codex_query))
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
    print(
        json.dumps(
            {
                "blank": len(blank),
                "already_copied": len(copied),
                "sessions": len(timelines),
                "queued": len(copies),
                "unmatched": unmatched,
                "sent_ok": sent,
                "failed": failed,
                "dry_run": args.dry_run,
            },
            sort_keys=True,
        )
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
