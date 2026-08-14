#!/usr/bin/env python3
"""Rank ALL local sessions (Claude Code, Codex, OMP) by total tokens and
print the tail. Real spend concentrates in a handful of outlier sessions,
not the average one - this is the "check the tails" companion to
token_audit.py, which only looks at a single session at a time.

Usage: top_sessions.py [N]   (default N=5 per tool, 20 overall)

Fixes the same Claude-Code dedup bug as token_audit.py: one JSONL line is
written per content block (thinking/text/tool_use), but every block sharing
a message.id carries the SAME usage snapshot - summing raw lines double or
triple counts. Dedupe by message.id before summing.

Deliberately does not touch Cursor (no local token data - see token_audit.py)
or remote machines (SSH scanning is a separate, explicitly-confirmed step).
"""
import json, sys, glob, os, time


def scan_claude(path):
    seen = set()
    tot = 0
    try:
        with open(path, errors="ignore") as f:
            for line in f:
                if '"type":"assistant"' not in line and '"type": "assistant"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("type") != "assistant":
                    continue
                msg = d.get("message", {})
                mid = msg.get("id")
                if mid in seen:
                    continue
                seen.add(mid)
                u = msg.get("usage", {})
                tot += u.get("input_tokens", 0) + u.get("output_tokens", 0) + \
                       u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
    except (OSError, UnicodeDecodeError):
        return 0
    return tot


def scan_codex(path):
    last = 0
    try:
        with open(path, errors="ignore") as f:
            for line in f:
                if '"token_count"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("type") != "event_msg":
                    continue
                p = d.get("payload", {})
                if p.get("type") != "token_count":
                    continue
                tu = (p.get("info") or {}).get("total_token_usage")
                if tu:
                    last = tu.get("total_tokens", last)
    except (OSError, UnicodeDecodeError):
        return 0
    return last


def scan_omp(path):
    tot = 0
    cost = 0.0
    try:
        with open(path, errors="ignore") as f:
            for line in f:
                if '"usage"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("type") != "message":
                    continue
                u = d.get("message", {}).get("usage")
                if not u:
                    continue
                tot += u.get("totalTokens", 0)
                cost += (u.get("cost") or {}).get("total", 0)
    except (OSError, UnicodeDecodeError):
        return 0, 0.0
    return tot, cost


def main():
    top_n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    t0 = time.time()
    claude_files = glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl"))
    codex_files = glob.glob(os.path.expanduser("~/.codex/sessions/*/*/*/*.jsonl"))
    omp_files = glob.glob(os.path.expanduser("~/.omp/agent/sessions/**/*.jsonl"), recursive=True)

    print(f"scanning {len(claude_files)} claude, {len(codex_files)} codex, {len(omp_files)} omp files", file=sys.stderr)

    results = []
    for p in claude_files:
        tot = scan_claude(p)
        if tot:
            results.append(("claude", p, tot, None))
    for p in codex_files:
        tot = scan_codex(p)
        if tot:
            results.append(("codex", p, tot, None))
    for p in omp_files:
        tot, cost = scan_omp(p)
        if tot:
            results.append(("omp", p, tot, cost))

    results.sort(key=lambda r: -r[2])
    print(f"done in {time.time()-t0:.0f}s, {len(results)} sessions with usage data", file=sys.stderr)

    print(f"\n=== TOP {top_n*4} SESSIONS OVERALL (by total tokens) ===")
    for src, p, tot, cost in results[:top_n * 4]:
        costs = f"  (${cost:.2f} OMP-reported)" if cost else ""
        print(f"  {tot:>14,}  [{src}]  {p}{costs}")

    for source in ("claude", "codex", "omp"):
        sub = [r for r in results if r[0] == source]
        print(f"\n=== TOP {top_n} {source.upper()} SESSIONS ===")
        for src, p, tot, cost in sub[:top_n]:
            costs = f"  (${cost:.2f})" if cost else ""
            print(f"  {tot:>14,}  {p}{costs}")


if __name__ == "__main__":
    main()
