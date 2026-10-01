from __future__ import annotations

import json
import os
import sys
import threading
import urllib.error
import urllib.request
from typing import Mapping

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_flags"))

import flags  # noqa: E402

EVENT_NAME = "catstack_hook_event"
API_KEY_ENV = "CATSTACK_POSTHOG_API_KEY"
HOST_ENV = "CATSTACK_POSTHOG_HOST"
DEFAULT_HOST = "https://us.i.posthog.com"
PUBLISH_FIELDS = (
    "hook",
    "harness",
    "rule_id",
    "action",
    "mode",
    "machine",
    "session_id",
    "model",
    "duration_ms",
    "ts",
)


def _flag_value(name: str) -> str:
    found = flags.resolve_flag(name, os.environ, None)
    return (found.value or "").strip()


def publish_rows(rows: list[dict[str, object]]) -> None:
    """Best-effort PostHog capture. No-op without CATSTACK_POSTHOG_API_KEY."""
    api_key = _flag_value(API_KEY_ENV)
    if not api_key or not rows:
        return
    host = (_flag_value(HOST_ENV) or DEFAULT_HOST).rstrip("/")
    payloads = [_capture_body(api_key, row) for row in rows]
    thread = threading.Thread(
        target=_post_batch,
        args=(host, payloads),
        name="catstack-posthog",
        daemon=True,
    )
    thread.start()


def _capture_body(api_key: str, row: Mapping[str, object]) -> dict[str, object]:
    properties = {key: row.get(key, "") for key in PUBLISH_FIELDS}
    properties["$geoip_disable"] = True
    distinct = str(row.get("session_id") or row.get("machine") or "catstack")
    return {
        "api_key": api_key,
        "event": EVENT_NAME,
        "distinct_id": distinct,
        "properties": properties,
        "timestamp": str(row.get("ts") or ""),
    }


def _post_batch(host: str, payloads: list[dict[str, object]]) -> None:
    for payload in payloads:
        try:
            data = json.dumps(payload).encode("utf-8")
            request = urllib.request.Request(
                f"{host}/capture/",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=1.5) as response:
                response.read(64)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            continue
