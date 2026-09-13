#!/usr/bin/env python3
"""Sum a Claude Code session's REAL subagent fan-out cost.

Usage:
    subagent_cost.py <session-jsonl-path-or-session-dir>

Why this exists: top_sessions.py ranks every local *.jsonl file by size, with
no notion of "this file belongs to that session's fan-out." A background
Bash task's <output-file> path (shown in task-notifications) looks like
<session-dir>/tasks/<id>.output and can share a UUID-shaped directory name
with an *unrelated* top-level session transcript that happens to reuse the
same session-dir naming scheme on a later day. Matching by UUID substring
alone, with no timestamp check, can attribute a totally unrelated session's
tokens to this session's subagent spend -- verified to actually happen: a
Cost-lens review on 2026-08-15 attributed 483M tokens from a stale file
(last event 2026-08-15T05:17:06Z) to a session whose own Agent() calls
didn't fire until 2026-08-15T20:04:32Z, a 14+ hour gap. Real subagents are
Task-tool children, and Claude Code writes their transcripts to
<session-dir>/subagents/agent-<id>.jsonl with a matching
agent-<id>.meta.json sidecar -- that directory, never top_sessions.py's
flat ranking, is the source of truth for "what did this session's
subagents cost."

This script sums exactly those files (via token_audit.audit_claude, so the
same message-id dedup logic applies) and reports total tokens per agent
and a grand total, with each agent's meta.json description if present.

The context-cost report is a synthetic-evaluation seam: it attributes the
parent's spend separately from each child's output and cache context, while
retaining the first sidechain user row as the parent instruction that
triggered that child. It reports token counts only; it never estimates dollars.
"""
import json
import os
import sys
from io import StringIO
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from token_audit import audit_claude  # noqa: E402


USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def resolve_subagents_dir(session_path):
    """Accept either a session .jsonl path or its <session-dir> directly."""
    if os.path.isdir(session_path):
        candidate = os.path.join(session_path, "subagents")
    else:
        session_dir = session_path[:-len(".jsonl")] if session_path.endswith(".jsonl") else session_path
        candidate = os.path.join(session_dir, "subagents")
    return candidate


def load_meta(jsonl_path):
    meta_path = jsonl_path[:-len(".jsonl")] + ".meta.json"
    if not os.path.isfile(meta_path):
        return {}
    try:
        with open(meta_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _assistant_dimensions(path):
    """Return deduped child-turn dimensions and the first parent trigger."""
    messages = {}
    trigger_text = None
    for row in _read_jsonl(path):
        if row.get("type") == "user" and trigger_text is None:
            content = row.get("message", {}).get("content")
            if isinstance(content, str):
                trigger_text = content
            elif isinstance(content, list):
                text = "\n".join(
                    block.get("text", "") for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                ).strip()
                if text:
                    trigger_text = text
        if row.get("type") != "assistant":
            continue
        message = row.get("message", {})
        message_id = message.get("id")
        if message_id not in messages:
            messages[message_id] = {"usage": {field: 0 for field in USAGE_FIELDS}, "tools": []}
        record = messages[message_id]
        usage = message.get("usage", {})
        for field in USAGE_FIELDS:
            record["usage"][field] = max(record["usage"][field], usage.get(field, 0))
        record["tools"].extend(
            block.get("name") for block in message.get("content", []) or []
            if isinstance(block, dict) and block.get("type") == "tool_use"
        )
    bash_turns = sum("Bash" in record["tools"] for record in messages.values())
    return {
        "trigger_text": trigger_text,
        "turns": len(messages),
        "bash_turns": bash_turns,
        "non_bash_turns": len(messages) - bash_turns,
    }


def _read_jsonl(path):
    with open(path) as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                yield row


def analyze_context_cost(session_path, parent_spend=None):
    """Pure, token-only attribution of one parent and its direct children."""
    import contextlib
    from io import StringIO

    parent_path = session_path
    if os.path.isdir(session_path):
        parent_path = os.path.join(
            os.path.dirname(session_path), os.path.basename(session_path) + ".jsonl"
        )
    if parent_spend is None:
        with contextlib.redirect_stdout(StringIO()):
            parent_stats = audit_claude(parent_path, include_subagents=False)
        parent_spend = parent_stats["total"] if parent_stats else 0

    children = []
    for path in sorted(
        os.path.join(resolve_subagents_dir(session_path), name)
        for name in os.listdir(resolve_subagents_dir(session_path))
        if name.startswith("agent-") and name.endswith(".jsonl")
    ) if os.path.isdir(resolve_subagents_dir(session_path)) else []:
        with contextlib.redirect_stdout(StringIO()):
            stats = audit_claude(path, include_subagents=False)
        if not stats:
            continue
        dimensions = _assistant_dimensions(path)
        children.append({
            "file": os.path.basename(path),
            "trigger_text": dimensions["trigger_text"],
            "spend": stats["total"],
            "output": stats["output"],
            "cache_read": stats["cache_read"],
            "cache_creation": stats["cache_creation"],
            "turns": dimensions["turns"],
            "bash_turns": dimensions["bash_turns"],
            "non_bash_turns": dimensions["non_bash_turns"],
        })

    return {
        "parent_spend": parent_spend,
        "child_spend": sum(child["spend"] for child in children),
        "child_output": sum(child["output"] for child in children),
        "child_cache_read": sum(child["cache_read"] for child in children),
        "child_cache_creation": sum(child["cache_creation"] for child in children),
        "child_count": len(children),
        "child_turns": sum(child["turns"] for child in children),
        "first_trigger_text": children[0]["trigger_text"] if children else None,
        "bash_turns": sum(child["bash_turns"] for child in children),
        "non_bash_turns": sum(child["non_bash_turns"] for child in children),
        "children": children,
    }


def agent_file_timestamp_range(path):
    """First and last 'timestamp' field seen in the file, if any."""
    first = last = None
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = d.get("timestamp")
                if not ts:
                    continue
                if first is None:
                    first = ts
                last = ts
    except OSError:
        pass
    return first, last


def sum_subagent_cost(session_path):
    subagents_dir = resolve_subagents_dir(session_path)
    if not os.path.isdir(subagents_dir):
        print(f"No subagents/ directory found at {subagents_dir}")
        print("Either this session spawned no Task-tool subagents, or you passed the wrong path.")
        return None

    agent_files = sorted(
        f for f in os.listdir(subagents_dir)
        if f.startswith("agent-") and f.endswith(".jsonl")
    )
    if not agent_files:
        print(f"subagents/ directory exists at {subagents_dir} but has no agent-*.jsonl files.")
        return None

    rows = []
    grand_total = 0
    for fname in agent_files:
        path = os.path.join(subagents_dir, fname)
        meta = load_meta(path)
        buf = StringIO()
        with redirect_stdout(buf):
            stats = audit_claude(path)
        if not stats:
            continue
        first_ts, last_ts = agent_file_timestamp_range(path)
        rows.append({
            "file": fname,
            "description": meta.get("description", "(no meta.json description)"),
            "total": stats["total"],
            "n_assistant": stats["n_assistant"],
            "n_errors": stats["n_errors"],
            "first_ts": first_ts,
            "last_ts": last_ts,
        })
        grand_total += stats["total"]

    rows.sort(key=lambda r: r["total"], reverse=True)

    print(f"=== Real subagent fan-out for {subagents_dir} ===")
    print(f"{len(rows)} agent transcript(s) found\n")
    for r in rows:
        share = (r["total"] / grand_total * 100) if grand_total else 0
        print(f"  {r['total']:>15,} tokens ({share:5.1f}%)  {r['n_assistant']:>4} turns  "
              f"{r['n_errors']:>2} errors  {r['file']}")
        print(f"      {r['description']}")
        print(f"      active {r['first_ts']} .. {r['last_ts']}")
    print(f"\nGRAND TOTAL: {grand_total:,} tokens across {len(rows)} subagent(s)")
    print("\nDo not cross-check this number against top_sessions.py's flat ranking by UUID "
          "substring match -- that comparison is exactly what produced a wrong 483M-token "
          "figure before. This script's total, from the real subagents/ directory, is the "
          "one to report.")
    return grand_total


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    result = sum_subagent_cost(sys.argv[1])
    if result is not None:
        report = analyze_context_cost(sys.argv[1])
        print("\n=== Subagent context-cost eval ===")
        for key in ("parent_spend", "child_spend", "child_output", "child_cache_read",
                    "child_cache_creation", "child_count", "child_turns", "bash_turns",
                    "non_bash_turns", "first_trigger_text"):
            print(f"{key}={report[key]}")
    sys.exit(0 if result is not None else 1)


if __name__ == "__main__":
    main()
