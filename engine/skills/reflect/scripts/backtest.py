#!/usr/bin/env python3
"""Frustration-signal backtest runner.

Runs token_audit's frustration detector against REAL local transcripts and
prints one summary line per session. The transcripts stay local — the
fixtures policy in cost-audit.md forbids committing real user transcripts —
so this runner is the committed, repeatable half of the backtest and the
data is whatever exists on the current machine.

This is how the 2026-08-17 detector change was validated: 13/58 flagged on
the motivating OMP session (matching the hand audit) and 3 genuine
"you are thrashing" accusation hits on a prior 124MB Claude session.

Usage:
  python3 skills/reflect/scripts/backtest.py                  # newest 5 sessions per tool
  python3 skills/reflect/scripts/backtest.py a.jsonl b.jsonl  # explicit files
  python3 skills/reflect/scripts/backtest.py --limit 10 --verbose
"""
import glob
import io
import json
import os
import sys
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import token_audit  # noqa: E402


def sniff_mode(path, max_lines=50):
    """Claude Code lines carry type user/assistant; OMP lines carry
    type=message with a role inside. First recognizable line wins."""
    try:
        with open(path) as f:
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = d.get("type")
                if t in ("user", "assistant"):
                    return "claude"
                if t == "message":
                    return "omp"
    except OSError:
        return None
    return None


def discover(limit):
    claude = glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl"))
    omp = glob.glob(os.path.expanduser("~/.omp/agent/sessions/**/*.jsonl"), recursive=True)
    tmp_iso = glob.glob(os.path.join(os.environ.get("TMPDIR", "/tmp"), "omp-agent-iso/*/sessions/*/*.jsonl"))
    omp = [p for p in omp + tmp_iso if "merge-clones" not in p and "--private-tmp--" not in p]
    found = []
    for group in (claude, omp):
        group.sort(key=os.path.getmtime, reverse=True)
        found.extend(group[:limit])
    return found


def summarize(path, verbose=False):
    mode = sniff_mode(path)
    if mode is None:
        return f"SKIP (unrecognized format) {path}"
    audit = token_audit.audit_claude if mode == "claude" else token_audit.audit_omp
    try:
        with redirect_stdout(io.StringIO()):
            result = audit(path)
    except Exception as e:  # per-file fail-soft: one broken transcript shouldn't kill the sweep
        return f"ERROR {os.path.basename(path)}: {e}"
    fr = result["frustration"]
    kinds = ",".join(f"{k}:{v}" for k, v in sorted(fr["kinds"].items(), key=lambda kv: -kv[1])) or "-"
    peak = f" peak={fr['peak_window'][0]}..{fr['peak_window'][1]}" if fr["peak_window"] else ""
    line = (
        f"{mode:6} {os.path.basename(path)[:52]:52} "
        f"flagged={fr['count']}/{fr['n_user_messages']} "
        f"interruptions={fr['interruptions']} kinds={kinds}{peak}"
    )
    if verbose and fr["flagged"]:
        line += "\n" + "\n".join(
            f"    [{f['index']}] {f['ts']} {f['kinds']}: {f['excerpt'][:70]!r}"
            for f in fr["flagged"]
        )
    return line


def main(argv):
    args = list(argv[1:])
    verbose = "--verbose" in args
    args = [a for a in args if a != "--verbose"]
    limit = 5
    if "--limit" in args:
        i = args.index("--limit")
        try:
            limit = int(args[i + 1])
        except (IndexError, ValueError):
            print("--limit requires an integer", file=sys.stderr)
            return 1
        del args[i:i + 2]
    paths = args or discover(limit)
    if not paths:
        print("no transcripts found", file=sys.stderr)
        return 1
    for p in paths:
        print(summarize(p, verbose=verbose))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
