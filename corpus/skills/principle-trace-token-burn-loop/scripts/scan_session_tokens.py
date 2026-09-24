#!/usr/bin/env python3
"""Fleet-wide per-session token scan for token-burn analysis.

Companion to engine/skills/reflect/scripts/token_audit.py: token_audit is a
per-session deep dive (pricing, thrash flags); this script is the fleet-level
rollup — scan whole session-store directories, emit one JSONL row per session
file, and let the caller aggregate (by machine, agent, workload class).

Usage:
    scan_session_tokens.py <dir-or-glob> [more roots...]
    scan_session_tokens.py --summary <dir> [...]     # aggregate table instead of rows
    cat scan_session_tokens.py | ssh host python3 - ~/.invoker/agent-sessions \
        ~/.claude/projects ~/.codex/sessions > rows.remote.jsonl

Formats handled (all verified against real session files, 2026-09):
  - codex exec stdout JSONL (invoker ~/.invoker/agent-sessions/*.jsonl):
      usage lands on type=turn.completed / thread.completed rows
      {usage:{input_tokens, cached_input_tokens, output_tokens}}
  - codex rollout JSONL (~/.codex/sessions/**): type=token_usage_record rows
      carry per-turn payload.usage (token_count event_msg rows are cumulative
      and would double-count — they are ignored).
  - claude JSONL (~/.claude/projects/**): assistant rows carry
      message.usage{input_tokens, output_tokens, cache_read_input_tokens,
      cache_creation_input_tokens}.
  - OMP JSONL (~/.omp/agent/sessions/**): assistant rows carry
      usage.{input,output,cacheRead,cacheWrite}.

Note: input_tokens semantics differ by harness. Codex input INCLUDES cached
tokens (uncached = input - cached_input_tokens). Claude input EXCLUDES
cache reads (uncached = input_tokens). Rows are emitted raw; the aggregator
(--summary) computes both gross and uncached-equivalent per bucket.

Known upstream undercount: Invoker's extractCodexUsage reads `cached_tokens`
but codex writes `cached_input_tokens` (packages/execution-engine/src/
codex-session.ts) — `query cost` therefore reports 0 cached and misses
sessions not linked via attempts.agent_session_id (~95% of volume).
"""
import json, glob, os, sys
from collections import defaultdict

def classify(head, path):
    """Workload bucket from the first ~400KB of a session + its path."""
    if 'llm-judge' in path:
        return 'llm-judge-one-shot'
    h = head[:400000]
    if ('loop-driver.sh' in h or 'mergify_admin_requeue' in h
            or 'battle-loop' in h or 'mergify-admin-requeue' in h):
        return 'pr-babysit-loop'
    if ('A build/test command failed' in h or 'Fix only the failing check' in h
            or 'fix-ci' in h):
        return 'fix-ci-autofix'
    if 'worker-session-mine' in h or 'session-mine' in h or 'session_mine' in h:
        return 'session-mining'
    if 'invoker-agent-prompt' in h or 'Review claim:' in h or 'Safety invariant:' in h:
        return 'invoker-task'
    if 'plan-to-invoker' in h or 'planning session' in h.lower():
        return 'planning'
    return 'other'

def scan_file(fp):
    inp = cached = cw = out = 0
    agent = None
    head = ''
    n = 0
    try:
        with open(fp, errors='replace') as fh:
            for line in fh:
                n += 1
                if n <= 400:
                    head += line
                if 'turn.completed' in line or 'thread.completed' in line:
                    try:
                        u = json.loads(line).get('usage')
                    except Exception:
                        u = None
                    if isinstance(u, dict):
                        agent = agent or 'codex'
                        inp += u.get('input_tokens', 0)
                        cached += u.get('cached_input_tokens', u.get('cached_tokens', 0) or 0)
                        cw += u.get('cache_write_input_tokens', 0)
                        out += u.get('output_tokens', 0)
                    continue
                if 'token_usage_record' in line:
                    try:
                        u = json.loads(line).get('payload', {}).get('usage')
                    except Exception:
                        u = None
                    if isinstance(u, dict):
                        agent = agent or 'codex'
                        inp += u.get('input_tokens', 0)
                        cached += u.get('cached_input_tokens', 0)
                        cw += u.get('cache_write_input_tokens', 0)
                        out += u.get('output_tokens', 0)
                    continue
                if '"usage"' in line:
                    try:
                        e = json.loads(line)
                    except Exception:
                        continue
                    m = e.get('message')
                    u = (m or {}).get('usage') if isinstance(m, dict) else e.get('usage')
                    if not isinstance(u, dict):
                        continue
                    if 'cacheRead' in u or 'cacheWrite' in u:  # OMP
                        agent = agent or 'omp'
                        inp += u.get('input', 0)
                        cached += u.get('cacheRead', 0)
                        cw += u.get('cacheWrite', 0)
                        out += u.get('output', 0)
                    elif 'cache_read_input_tokens' in u or 'cache_creation_input_tokens' in u or m:
                        agent = agent or 'claude'
                        inp += u.get('input_tokens', 0)
                        cached += u.get('cache_read_input_tokens', 0)
                        cw += u.get('cache_creation_input_tokens', 0)
                        out += u.get('output_tokens', 0)
    except Exception:
        return None
    if not (inp or cached or cw or out):
        return None
    sid = os.path.basename(fp)
    if sid.endswith('.jsonl'):
        sid = sid[:-6]
    return {
        'sid': sid, 'agent': agent or 'unknown', 'cls': classify(head, fp),
        'inp': inp, 'cached': cached, 'cw': cw, 'out': out,
        'mtime': int(os.path.getmtime(fp)), 'path': fp,
    }

def uncached_equiv(r):
    if r['agent'] == 'codex':
        return max(r['inp'] - r['cached'], 0) + r['out']
    return r['inp'] + r['out']

def gross(r):
    # codex input_tokens already includes cached — do NOT add cached again.
    # claude/omp input excludes cache reads/writes, so they add on top.
    if r['agent'] == 'codex':
        return r['inp'] + r['out']
    return r['inp'] + r['out'] + r['cached'] + r['cw']

def main():
    args = sys.argv[1:]
    summary = '--summary' in args
    args = [a for a in args if a != '--summary']
    files = []
    for root in args:
        root = os.path.expanduser(root)
        if os.path.isdir(root):
            files += glob.glob(os.path.join(root, '**', '*.jsonl'), recursive=True)
        elif os.path.isfile(root):
            files.append(root)
    rows = [r for r in (scan_file(f) for f in files) if r]
    if not summary:
        for r in rows:
            print(json.dumps(r), flush=True)
        return
    # dedupe by sid (pushed copies of remote sessions exist locally)
    best = {}
    for r in rows:
        if r['sid'] not in best or gross(r) > gross(best[r['sid']]):
            best[r['sid']] = r
    rows = list(best.values())
    agg = defaultdict(lambda: [0, 0, 0.0])
    for r in rows:
        k = (r['agent'], r['cls'])
        agg[k][0] += gross(r)
        agg[k][1] += 1
        agg[k][2] += uncached_equiv(r)
    tot_g = sum(v[0] for v in agg.values()) or 1
    tot_u = sum(v[2] for v in agg.values()) or 1
    print(f'{"agent":7}{"class":22}{"gross_tokens":>16} {"share":>6} {"sessions":>9} {"uncached_eq":>14} {"share":>6}')
    for (a, c), (g, n, u) in sorted(agg.items(), key=lambda kv: -kv[1][0]):
        print(f'{a:7}{c:22}{g:>16,} {100*g/tot_g:5.1f}% {n:>9,} {u:>14,.0f} {100*u/tot_u:5.1f}%')
    print(f'{"TOTAL":29}{tot_g:>16,} {"100%":>6} {sum(v[1] for v in agg.values()):>9,} {tot_u:>14,.0f}')

if __name__ == '__main__':
    main()
