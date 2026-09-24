#!/usr/bin/env python3
"""Per-turn context-size series for a session file — the "sawtooth" view.

The question this answers: is a session expensive because it did a lot of
work, or because it lived a long time with a big context? Every model call
re-sends the whole transcript, so cost ~= sum over turns of context size.
This script extracts the per-call context size (input tokens incl. cache
reads) and detects /clear / compaction cycles (the drops in the sawtooth).

Usage:
    context_growth.py <session.jsonl> [more files...]           # JSONL rows
    context_growth.py --summary <session.jsonl> [...]           # one line/file
    cat context_growth.py | ssh host python3 - --summary file...

Row format (default mode), one per model call:
    {"ts": ..., "seq": n, "ctx": <input+cache_read>, "out": n, "uncached": n}

Summary fields:
    turns        model calls observed
    peak_ctx     largest single-call context
    clears       number of >40% context drops (sawtooth cycles)
    avg_ctx      mean context per call
    gross        sum of ctx over calls (the resend total)
    span_h       first-to-last timestamp hours
Formats:
  - claude JSONL: assistant rows -> message.usage (ctx = input_tokens +
    cache_read_input_tokens + cache_creation_input_tokens)
  - codex rollout JSONL: event_msg token_count rows -> payload.info.
    last_token_usage is the per-call usage; total_token_usage is cumulative
    (ignored to avoid double counting)
  - codex exec JSONL (~/.invoker/agent-sessions): only turn.completed totals
    exist — no per-call context. Emits a single summary row with gross =
    turn usage and a note; there is no series to plot.
"""
import json, os, signal, sys

CLEAR_DROP_RATIO = 0.6


def end_quietly_when_the_reader_stops():
    """Restore the default SIGPIPE so piping into `head` ends without a trace."""
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)


end_quietly_when_the_reader_stops()


def per_call_from_cumulative(total, prev_total):
    """Per-call usage for rollout rows that carry only a running total.

    Older codex rollouts omit last_token_usage, so the call's own usage is
    what the running total gained since the previous row.
    """
    prev = prev_total or {}
    return {k: max(total.get(k, 0) - prev.get(k, 0), 0)
            for k in ('input_tokens', 'output_tokens', 'cached_input_tokens')}


def series(fp):
    """Yield dicts {ts, ctx, out, uncached} per model call."""
    prev_total = None
    try:
        with open(fp, errors='replace') as fh:
            for line in fh:
                if 'usage' not in line and 'token_count' not in line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                ts = e.get('timestamp')
                p = e.get('payload')
                if isinstance(p, dict) and p.get('type') == 'token_count':
                    info = p.get('info') or {}
                    u = info.get('last_token_usage')
                    if not isinstance(u, dict):
                        tot = info.get('total_token_usage')
                        if isinstance(tot, dict):
                            u = per_call_from_cumulative(tot, prev_total)
                            prev_total = tot
                    if isinstance(u, dict) and (u.get('input_tokens') or u.get('output_tokens')):
                        inp = u.get('input_tokens', 0)
                        cached = u.get('cached_input_tokens', 0)
                        yield {'ts': ts, 'ctx': inp, 'out': u.get('output_tokens', 0),
                               'uncached': max(inp - cached, 0)}
                    continue
                if e.get('type') in ('turn.completed', 'thread.completed'):
                    u = e.get('usage')
                    if isinstance(u, dict):
                        inp = u.get('input_tokens', 0)
                        cached = u.get('cached_input_tokens', u.get('cached_tokens', 0) or 0)
                        yield {'ts': ts, 'ctx': inp, 'out': u.get('output_tokens', 0),
                               'uncached': max(inp - cached, 0), 'whole_turn': True}
                    continue
                m = e.get('message')
                if isinstance(m, dict) and m.get('role') == 'assistant':
                    u = m.get('usage')
                    if isinstance(u, dict):
                        ctx = (u.get('input_tokens', 0)
                               + u.get('cache_read_input_tokens', 0)
                               + u.get('cache_creation_input_tokens', 0))
                        yield {'ts': ts, 'ctx': ctx,
                               'out': u.get('output_tokens', 0),
                               'uncached': u.get('input_tokens', 0)}
    except Exception as ex:
        yield {'error': str(ex)}


def summarize(fp):
    """One row per session: turns, peak and average context, clears, gross.

    A call whose context falls below CLEAR_DROP_RATIO of the call before it
    is counted as a clear: that is what /clear or a compaction looks like in
    the series, and it is the down-stroke of the sawtooth.
    """
    pts = [p for p in series(fp) if 'ctx' in p]
    r = {'path': fp, 'sid': os.path.basename(fp).replace('.jsonl', ''),
         'turns': len(pts)}
    if not pts:
        r['note'] = 'no per-call usage rows'
        return r
    if any(p.get('whole_turn') for p in pts):
        r['note'] = 'exec format: whole-turn totals only, no per-call series'
    ctxs = [p['ctx'] for p in pts]
    r['peak_ctx'] = max(ctxs)
    r['avg_ctx'] = int(sum(ctxs) / len(ctxs))
    r['gross'] = sum(ctxs)
    r['clears'] = sum(1 for a, b in zip(ctxs, ctxs[1:])
                      if b < a * CLEAR_DROP_RATIO and a > 50000)
    r['uncached'] = sum(p.get('uncached', 0) for p in pts)
    r['out'] = sum(p['out'] for p in pts)
    tss = [p['ts'] for p in pts if p.get('ts')]
    if len(tss) >= 2:
        try:
            from datetime import datetime
            a = datetime.fromisoformat(tss[0].replace('Z', '+00:00'))
            b = datetime.fromisoformat(tss[-1].replace('Z', '+00:00'))
            r['span_h'] = round((b - a).total_seconds() / 3600, 1)
        except Exception:
            pass
    return r


def main():
    args = sys.argv[1:]
    summary = '--summary' in args
    files = [os.path.expanduser(a) for a in args if a != '--summary']
    for fp in files:
        if summary:
            print(json.dumps(summarize(fp)), flush=True)
        else:
            for i, p in enumerate(series(fp)):
                p['seq'] = i
                p['path'] = fp
                print(json.dumps(p), flush=True)


if __name__ == '__main__':
    main()
