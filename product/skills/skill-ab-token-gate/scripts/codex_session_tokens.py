#!/usr/bin/env python3
"""Extract Codex rollout token usage and collaboration children."""
from __future__ import annotations

import json
import re
from pathlib import Path


def last_total_usage(path: Path) -> dict | None:
    last = None
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if "total_token_usage" not in line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = ev.get("payload") if isinstance(ev, dict) else None
            if not isinstance(payload, dict):
                continue
            info = payload.get("info") if isinstance(payload.get("info"), dict) else payload
            usage = info.get("total_token_usage") if isinstance(info, dict) else None
            if isinstance(usage, dict) and "input_tokens" in usage:
                last = usage
    return last


def spawn_agent_calls(path: Path) -> int:
    text = path.read_text(encoding="utf-8", errors="replace")
    return text.count('"name":"spawn_agent"')


def discover_child_paths(parent: Path, sessions_root: Path) -> list[Path]:
    ids: list[str] = []
    with parent.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            for match in re.finditer(r'"agent_thread_id"\s*:\s*"([^"]+)"', line):
                tid = match.group(1)
                if tid not in ids:
                    ids.append(tid)
    children: list[Path] = []
    for tid in ids:
        matches = sorted(sessions_root.rglob(f"rollout-*-{tid}.jsonl"))
        if matches:
            children.append(matches[-1])
    return children


def uncached_plus_output(usage: dict | None) -> int:
    if not usage:
        return 0
    return (
        int(usage.get("input_tokens", 0))
        - int(usage.get("cached_input_tokens", 0))
        + int(usage.get("output_tokens", 0))
    )


def score_parent(parent: Path, sessions_root: Path) -> dict:
    parent_usage = last_total_usage(parent)
    children = []
    child_total = 0
    child_unc = 0
    for child in discover_child_paths(parent, sessions_root):
        usage = last_total_usage(child)
        children.append({"path": str(child), "usage": usage})
        if usage:
            child_total += int(usage.get("total_tokens") or 0)
            child_unc += uncached_plus_output(usage)
    parent_total = int((parent_usage or {}).get("total_tokens") or 0)
    text = parent.read_text(encoding="utf-8", errors="replace")
    return {
        "parent_session": str(parent),
        "parent_usage": parent_usage,
        "children": children,
        "child_total_tokens": child_total,
        "inclusive_total_tokens": parent_total + child_total,
        "inclusive_uncached_plus_output": uncached_plus_output(parent_usage) + child_unc,
        "spawn_agent_calls": spawn_agent_calls(parent),
        "capture_helper": "capture_tool_result.py" in text,
    }
