#!/usr/bin/env python3
"""Append-only DORA measurement history (aggregates only).

Weekly points for trend charts. Dedupe by UTC ISO calendar week.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

GATED_METRICS = (
    ("lead_pickup", "median_seconds"),
    ("mttr", "median_seconds"),
    ("rework_rate", "rate"),
    ("deploy_frequency", "per_day"),
)


def utc_week_key(captured_at: str) -> str:
    """Return YYYY-Www for UTC calendar week (ISO)."""
    text = captured_at.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def snapshot_from_measurement(measurement: dict[str, Any]) -> dict[str, Any]:
    """Compact history row from a full baseline-shaped measurement."""
    windows_out: dict[str, Any] = {}
    for label, win in (measurement.get("windows") or {}).items():
        slim: dict[str, Any] = {}
        for group, field in GATED_METRICS:
            blob = win.get(group) or {}
            slim[group] = {field: blob.get(field)}
            if group == "rework_rate":
                slim[group]["started"] = blob.get("started")
                slim[group]["failed"] = blob.get("failed")
            if group == "deploy_frequency":
                slim[group]["merged"] = blob.get("merged")
        windows_out[label] = slim
    return {
        "captured_at": measurement.get("captured_at"),
        "version": measurement.get("version", 2),
        "windows": windows_out,
    }


def load_history(path: str) -> dict[str, Any]:
    if not os.path.isfile(path):
        return {"version": 1, "points": []}
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        return {"version": 1, "points": []}
    data.setdefault("version", 1)
    data.setdefault("points", [])
    return data


def save_history(path: str, history: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(history, handle, indent=2)
        handle.write("\n")


def append_point(
    history: dict[str, Any], point: dict[str, Any], *, replace_same_week: bool = True
) -> tuple[dict[str, Any], bool]:
    """Append or replace same UTC week. Returns (history, changed)."""
    points = list(history.get("points") or [])
    key = utc_week_key(str(point.get("captured_at") or ""))
    changed = False
    if replace_same_week:
        kept: list[dict[str, Any]] = []
        replaced = False
        for existing in points:
            ek = utc_week_key(str(existing.get("captured_at") or ""))
            if ek == key:
                kept.append(point)
                replaced = True
                changed = True
            else:
                kept.append(existing)
        if not replaced:
            kept.append(point)
            changed = True
        points = kept
    else:
        if any(utc_week_key(str(p.get("captured_at") or "")) == key for p in points):
            return history, False
        points.append(point)
        changed = True
    points.sort(key=lambda p: str(p.get("captured_at") or ""))
    history = dict(history)
    history["points"] = points
    history["version"] = history.get("version", 1)
    return history, changed
