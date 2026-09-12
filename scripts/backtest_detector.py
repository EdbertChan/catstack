#!/usr/bin/env python3
"""Replay one detector over real local transcripts and report what it catches.

    python3 scripts/backtest_detector.py --detector PATH:CALLABLE [--unit UNIT]
        [--limit N] [--verbose] [--json OUT] [TRANSCRIPT_OR_DIR ...]
    python3 scripts/backtest_detector.py --detector PATH:CALLABLE --compare REF
    python3 scripts/backtest_detector.py --detector PATH:CALLABLE --compare OTHER_PATH[:CALLABLE]

Units, and the call made for each:
  assistant  CALLABLE(text) for every assistant text block
  final      CALLABLE(text) for every turn-ending assistant reply
  user       CALLABLE(text) for every human-typed user message
  tool       CALLABLE({"tool_name", "tool_input"}) for every tool call; --tool narrows
  rows       CALLABLE(rows) once per session, rows yielding (line_index, row); it yields
             (key, text, verdict) or (key, text, verdict, near) per unit it judged

A truthy verdict is a hit. With no paths, the newest --limit sessions per source
(Claude Code, OMP) are scanned. Files are streamed and never leave this machine.
"""
from __future__ import annotations

import argparse
import glob
import importlib.util
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter

UNITS = ("assistant", "final", "user", "tool", "rows")
TEXT_UNITS = ("assistant", "final", "user")
SNIFF_LINES = 50
EXCERPT_WIDTH = 160
LABEL_WIDTH = 40
SYSTEM_PREFIXES = (
    "<",
    "[Request interrupted",
    "This session is being continued",
    "Base directory for this skill",
    "[IMPORTANT: User invoked",
)
PARAGRAPH_RE = re.compile(r"\n\s*\n")


class Detector:
    def __init__(self, fn, label: str):
        self.fn = fn
        self.label = label


def parse_spec(spec: str) -> tuple[str, str]:
    path, sep, name = spec.rpartition(":")
    if not sep or not path or not name:
        raise ValueError(f"detector must be PATH:CALLABLE, got {spec!r}")
    return path, name


def _sibling_names(directory: str) -> set[str]:
    names = set()
    for entry in os.listdir(directory):
        stem, ext = os.path.splitext(entry)
        if ext == ".py" or os.path.isdir(os.path.join(directory, entry)):
            names.add(stem)
    return names


def load_callable(path: str, name: str, label: str | None = None) -> Detector:
    full = os.path.abspath(path)
    if not os.path.isfile(full):
        raise ValueError(f"detector file not found: {label or path}")
    directory = os.path.dirname(full)
    siblings = _sibling_names(directory)
    stashed = {n: sys.modules.pop(n) for n in siblings if n in sys.modules}
    module_name = f"backtest_detector_{abs(hash((full, label)))}"
    spec = importlib.util.spec_from_file_location(module_name, full)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    sys.path.insert(0, directory)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(directory)
        for n in siblings:
            sys.modules.pop(n, None)
        sys.modules.update(stashed)
    fn = getattr(module, name, None)
    if not callable(fn):
        raise ValueError(f"{label or path} has no callable {name!r}")
    return Detector(fn, f"{label or path}:{name}")


def _git(cwd: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True)


def materialize_revision(path: str, ref: str) -> tuple[str, str]:
    full = os.path.realpath(path)
    top = _git(os.path.dirname(full), "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        raise ValueError(f"{path} is not inside a git repository, so {ref!r} cannot be resolved")
    root = os.path.realpath(top.stdout.decode().strip())
    if _git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").returncode != 0:
        raise ValueError(f"{ref!r} is neither a detector path nor a git revision")
    rel = os.path.relpath(full, root)
    archive = _git(root, "archive", "--format=tar", ref)
    if archive.returncode != 0:
        raise ValueError(f"git archive {ref} failed: {archive.stderr.decode().strip()}")
    tmp = tempfile.mkdtemp(prefix="backtest-detector-")
    subprocess.run(["tar", "-x", "-C", tmp], input=archive.stdout, check=True)
    return tmp, os.path.join(tmp, rel)


def resolve_baseline(candidate_path: str, candidate_name: str, compare: str, tmpdirs: list) -> Detector:
    if os.path.isfile(compare):
        return load_callable(compare, candidate_name)
    head, sep, tail = compare.rpartition(":")
    if sep and os.path.isfile(head):
        return load_callable(head, tail)
    tmp, path = materialize_revision(candidate_path, compare)
    tmpdirs.append(tmp)
    return load_callable(path, candidate_name, label=f"{candidate_path}@{compare}")


def discover(limit: int) -> list[str]:
    home = os.path.expanduser("~")
    claude = glob.glob(os.path.join(home, ".claude", "projects", "*", "*.jsonl"))
    omp = glob.glob(os.path.join(home, ".omp", "agent", "sessions", "**", "*.jsonl"), recursive=True)
    omp += glob.glob(os.path.join(os.environ.get("TMPDIR", "/tmp"), "omp-agent-iso", "*", "sessions", "*", "*.jsonl"))
    omp = [p for p in omp if "merge-clones" not in p and "--private-tmp--" not in p]
    found = []
    for group in (claude, omp):
        group.sort(key=os.path.getmtime, reverse=True)
        found.extend(group[:limit])
    return found


def expand(paths: list[str]) -> list[str]:
    out = []
    for p in paths:
        out.extend(sorted(glob.glob(os.path.join(p, "*.jsonl"))) if os.path.isdir(p) else [p])
    return out


def iter_rows(path: str):
    with open(path, encoding="utf-8", errors="ignore") as handle:
        for index, line in enumerate(handle):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                yield index, row


def sniff_format(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="ignore") as handle:
            for i, line in enumerate(handle):
                if i >= SNIFF_LINES:
                    break
                try:
                    kind = json.loads(line).get("type")
                except (json.JSONDecodeError, AttributeError):
                    continue
                if kind in ("user", "assistant"):
                    return "claude"
                if kind == "message":
                    return "omp"
    except OSError:
        return None
    return None


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def shape(row: dict, fmt: str) -> tuple[str | None, str, list]:
    if fmt == "omp":
        if row.get("type") != "message":
            return None, "", []
        msg = row.get("message") or {}
        role = msg.get("role")
        content = msg.get("content")
        if role == "toolResult":
            return "result", "", []
        if role not in ("user", "assistant"):
            return None, "", []
        tools = [
            (b.get("name"), b.get("arguments") or {})
            for b in (content if isinstance(content, list) else [])
            if isinstance(b, dict) and b.get("type") == "toolCall"
        ]
        return role, _content_text(content), tools
    kind = row.get("type")
    if kind not in ("user", "assistant"):
        return None, "", []
    content = (row.get("message") or {}).get("content")
    blocks = content if isinstance(content, list) else []
    if kind == "user" and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in blocks):
        return "result", "", []
    tools = [
        (b.get("name"), b.get("input") or {})
        for b in blocks
        if isinstance(b, dict) and b.get("type") == "tool_use"
    ]
    return kind, _content_text(content), tools


def _is_human(row: dict, text: str) -> bool:
    stripped = text.strip()
    if not stripped or row.get("isMeta") or row.get("isSidechain"):
        return False
    return not stripped.startswith(SYSTEM_PREFIXES)


def _tool_text(name, tool_input) -> str:
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if isinstance(command, str):
        return command
    return f"{name} {json.dumps(tool_input, sort_keys=True, default=str)}"


def _once(unit, seen: set[int]):
    digest = hash(unit[1])
    if digest not in seen:
        seen.add(digest)
        yield unit


def _final_units(rows, fmt: str):
    held = None
    seen: set[int] = set()
    for index, row in rows:
        role, text, _ = shape(row, fmt)
        if role is None:
            continue
        if held is not None and role == "user":
            yield from _once(held, seen)
        held = (index, text, (text,)) if role == "assistant" and text.strip() else None
    if held is not None:
        yield from _once(held, seen)


def units(rows, fmt: str, unit: str, tools: tuple[str, ...]):
    if unit == "final":
        yield from _final_units(rows, fmt)
        return
    for index, row in rows:
        role, text, calls = shape(row, fmt)
        if unit == "assistant" and role == "assistant" and text.strip():
            yield index, text, (text,)
        elif unit == "user" and role == "user" and _is_human(row, text):
            yield index, text, (text,)
        elif unit == "tool" and role == "assistant":
            for offset, (name, tool_input) in enumerate(calls):
                if tools and name not in tools:
                    continue
                payload = {"hook_event_name": "PreToolUse", "tool_name": name, "tool_input": tool_input}
                yield f"{index}.{offset}", _tool_text(name, tool_input), (payload,)


def _paragraph_probe(fn, text: str):
    paragraphs = [p for p in PARAGRAPH_RE.split(text) if p.strip()]
    if len(paragraphs) < 2:
        return None
    for para in paragraphs:
        verdict = fn(para)
        if verdict:
            return verdict
    return None


def judgments(detector: Detector, path: str, fmt: str, unit: str, tools: tuple[str, ...], near: Detector | None):
    if unit == "rows":
        for item in detector.fn(iter_rows(path)):
            if len(item) == 4:
                yield item
            else:
                key, text, verdict = item
                yield key, text, verdict, None
        return
    for key, text, call_args in units(iter_rows(path), fmt, unit, tools):
        verdict = detector.fn(*call_args)
        near_verdict = None
        if not verdict:
            if near is not None:
                near_verdict = near.fn(*call_args)
            elif unit in TEXT_UNITS:
                near_verdict = _paragraph_probe(detector.fn, text)
        yield key, text, verdict, near_verdict


def labels(verdict) -> list[str]:
    if isinstance(verdict, dict):
        return [f"{k}={v}" for k, v in verdict.items() if isinstance(v, (str, bool))]
    if isinstance(verdict, (list, tuple, set, frozenset)):
        return [str(v) for v in verdict]
    if verdict is True:
        return []
    return [str(verdict)]


def amounts(verdict) -> dict:
    if not isinstance(verdict, dict):
        return {}
    return {k: v for k, v in verdict.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}


def _clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def tags(verdict) -> list[str]:
    return [_clip(tag, LABEL_WIDTH) for tag in labels(verdict)]


def excerpt(text: str, verdict=None, width: int = EXCERPT_WIDTH) -> str:
    flat = " ".join(str(text).split())
    anchor = next((tag for tag in labels(verdict) if tag and tag.lower() in flat.lower()), "") if verdict else ""
    at = flat.lower().find(anchor.lower()) if anchor else -1
    start = max(0, min(at - width // 3, len(flat) - width)) if at > 0 else 0
    clip = flat[start:start + width]
    return ("…" if start else "") + clip + ("…" if start + width < len(flat) else "")


class Sample:
    def __init__(self, size: int, rng: random.Random):
        self.size = size
        self.rng = rng
        self.items: list = []
        self.seen = 0

    def add(self, item) -> None:
        self.seen += 1
        if len(self.items) < self.size:
            self.items.append(item)
            return
        slot = self.rng.randrange(self.seen)
        if slot < self.size:
            self.items[slot] = item


def _kinds(counter: Counter, top: int) -> str:
    shown = ",".join(f"{k}:{v}" for k, v in counter.most_common(top)) or "-"
    rest = len(counter) - top
    return f"{shown},+{rest} more" if rest > 0 else shown


def _amounts_text(counter: Counter) -> str:
    return "".join(f" {k}={v:g}" for k, v in sorted(counter.items()))


def _rate(hits: int, scanned: int) -> str:
    return f"{100.0 * hits / scanned:.2f}%" if scanned else "n/a"


def _print_sample(title: str, sample: Sample) -> None:
    print(f"{title} ({len(sample.items)} of {sample.seen}):")
    for session, key, label, text in sample.items:
        print(f"  {session}:{key}  [{label}]  {text}")


def run_single(detector: Detector, near: Detector | None, files: list[str], args) -> tuple[int, dict]:
    rng = random.Random(0)
    hit_sample, near_sample = Sample(args.samples, rng), Sample(args.samples, rng)
    totals = {"sessions": 0, "unchecked": 0, "errors": 0, "scanned": 0, "hits": 0, "near_misses": 0}
    kinds, sums = Counter(), Counter()
    report = []
    for path in files:
        totals["sessions"] += 1
        name = os.path.basename(path)
        fmt = sniff_format(path)
        if fmt is None:
            totals["unchecked"] += 1
            print(f"SKIP (unrecognized format) {path}")
            report.append({"path": path, "status": "unrecognized"})
            continue
        scanned = hits = near_count = 0
        s_kinds, s_sums = Counter(), Counter()
        s_hits, detail = [], []
        try:
            for key, text, verdict, near_verdict in judgments(detector, path, fmt, args.unit, args.tool, near):
                scanned += 1
                if verdict:
                    hits += 1
                    hit_tags = tags(verdict)
                    s_kinds.update(hit_tags)
                    s_sums.update(amounts(verdict))
                    label = ",".join(hit_tags) or "hit"
                    hit_sample.add((name[:12], key, label, excerpt(text, verdict)))
                    if args.verbose:
                        detail.append(f"    [{key}] {label}: {excerpt(text, verdict, 90)!r}")
                    if args.json_out:
                        s_hits.append({"key": key, "verdict": verdict, "excerpt": excerpt(text, verdict)})
                elif near_verdict:
                    near_count += 1
                    near_label = ",".join(tags(near_verdict)) or "near"
                    near_sample.add((name[:12], key, near_label, excerpt(text, near_verdict)))
        except Exception as exc:
            totals["unchecked"] += 1
            totals["errors"] += 1
            print(f"ERROR {name}: {type(exc).__name__}: {exc}")
            report.append({"path": path, "status": "error", "error": f"{type(exc).__name__}: {exc}"})
            continue
        totals["scanned"] += scanned
        totals["hits"] += hits
        totals["near_misses"] += near_count
        kinds.update(s_kinds)
        sums.update(s_sums)
        print(f"{fmt:6} {name[:52]:52} hits={hits}/{scanned} kinds={_kinds(s_kinds, 5)}{_amounts_text(s_sums)}")
        for line in detail:
            print(line)
        report.append({"path": path, "status": "ok", "format": fmt, "scanned": scanned, "hits": hits,
                       "near_misses": near_count, "kinds": dict(s_kinds), "amounts": dict(s_sums), "hit_units": s_hits})
    print()
    print(f"detector: {detector.label} unit={args.unit}")
    print(
        f"sessions={totals['sessions']} unchecked={totals['unchecked']} scanned={totals['scanned']} "
        f"hits={totals['hits']} hit_rate={_rate(totals['hits'], totals['scanned'])} "
        f"near_misses={totals['near_misses']}"
    )
    print(f"kinds: {_kinds(kinds, 12)}{_amounts_text(sums)}")
    _print_sample("hits", hit_sample)
    _print_sample("near-misses", near_sample)
    totals.update({"kinds": dict(kinds), "amounts": dict(sums)})
    return _exit_code(totals), {"detector": detector.label, "unit": args.unit, "totals": totals, "sessions": report}


def _collect(detector: Detector, path: str, fmt: str, args) -> tuple[int, dict]:
    scanned = 0
    hits = {}
    for key, text, verdict, _ in judgments(detector, path, fmt, args.unit, args.tool, None):
        scanned += 1
        if verdict:
            label = ",".join(tags(verdict)) or "hit"
            hits[key] = (label, excerpt(text, verdict))
    return scanned, hits


def run_compare(candidate: Detector, baseline: Detector, files: list[str], args) -> tuple[int, dict]:
    rng = random.Random(0)
    caught_sample, missed_sample = Sample(args.samples, rng), Sample(args.samples, rng)
    totals = {"sessions": 0, "unchecked": 0, "errors": 0, "scanned": 0, "baseline_scanned": 0,
              "candidate_hits": 0, "baseline_hits": 0, "newly_caught": 0, "newly_missed": 0, "unchanged": 0}
    report = []
    for path in files:
        totals["sessions"] += 1
        name = os.path.basename(path)
        fmt = sniff_format(path)
        if fmt is None:
            totals["unchecked"] += 1
            print(f"SKIP (unrecognized format) {path}")
            report.append({"path": path, "status": "unrecognized"})
            continue
        try:
            scanned, new_hits = _collect(candidate, path, fmt, args)
            base_scanned, old_hits = _collect(baseline, path, fmt, args)
        except Exception as exc:
            totals["unchecked"] += 1
            totals["errors"] += 1
            print(f"ERROR {name}: {type(exc).__name__}: {exc}")
            report.append({"path": path, "status": "error", "error": f"{type(exc).__name__}: {exc}"})
            continue
        caught = [k for k in new_hits if k not in old_hits]
        missed = [k for k in old_hits if k not in new_hits]
        same = len(new_hits) - len(caught)
        for key in caught:
            caught_sample.add((name[:12], key, *new_hits[key]))
        for key in missed:
            missed_sample.add((name[:12], key, *old_hits[key]))
        totals["scanned"] += scanned
        totals["baseline_scanned"] += base_scanned
        totals["candidate_hits"] += len(new_hits)
        totals["baseline_hits"] += len(old_hits)
        totals["newly_caught"] += len(caught)
        totals["newly_missed"] += len(missed)
        totals["unchanged"] += same
        print(
            f"{fmt:6} {name[:52]:52} hits={len(new_hits)}/{scanned} was={len(old_hits)}/{base_scanned} "
            f"caught={len(caught)} missed={len(missed)}"
        )
        if args.verbose:
            for key in caught:
                print(f"    + [{key}] {new_hits[key][0]}: {new_hits[key][1][:90]!r}")
            for key in missed:
                print(f"    - [{key}] {old_hits[key][0]}: {old_hits[key][1][:90]!r}")
        report.append({"path": path, "status": "ok", "format": fmt, "scanned": scanned, "baseline_scanned": base_scanned,
                       "candidate_hits": len(new_hits), "baseline_hits": len(old_hits),
                       "newly_caught": [{"key": k, "label": new_hits[k][0], "excerpt": new_hits[k][1]} for k in caught],
                       "newly_missed": [{"key": k, "label": old_hits[k][0], "excerpt": old_hits[k][1]} for k in missed],
                       "unchanged": same})
    print()
    print(f"candidate: {candidate.label} unit={args.unit}")
    print(f"baseline:  {baseline.label}")
    scanned_text = str(totals["scanned"])
    if totals["baseline_scanned"] != totals["scanned"]:
        scanned_text += f" (baseline {totals['baseline_scanned']})"
    print(
        f"sessions={totals['sessions']} unchecked={totals['unchecked']} scanned={scanned_text} "
        f"candidate_hits={totals['candidate_hits']} ({_rate(totals['candidate_hits'], totals['scanned'])}) "
        f"baseline_hits={totals['baseline_hits']} ({_rate(totals['baseline_hits'], totals['baseline_scanned'])})"
    )
    print(f"newly_caught={totals['newly_caught']} newly_missed={totals['newly_missed']} unchanged={totals['unchanged']}")
    _print_sample("newly caught", caught_sample)
    _print_sample("newly missed", missed_sample)
    return _exit_code(totals), {"candidate": candidate.label, "baseline": baseline.label, "unit": args.unit,
                                "totals": totals, "sessions": report}


def _exit_code(totals: dict) -> int:
    if totals["errors"] or totals["unchecked"] == totals["sessions"]:
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", help="transcripts or directories of *.jsonl; overrides discovery")
    ap.add_argument("--detector", required=True, help="PATH:CALLABLE")
    ap.add_argument("--unit", choices=UNITS, default="assistant")
    ap.add_argument("--tool", action="append", default=[], help="tool name to keep for --unit tool (repeatable)")
    ap.add_argument("--near", help="PATH:CALLABLE whose hits on a miss count as a near-miss")
    ap.add_argument("--compare", help="baseline: a git revision of the same file, or PATH[:CALLABLE]")
    ap.add_argument("--limit", type=int, default=5, help="newest sessions per source when discovering (default 5)")
    ap.add_argument("--samples", type=int, default=10, help="sample size for each printed list (default 10)")
    ap.add_argument("--verbose", action="store_true", help="list every hit under its session line")
    ap.add_argument("--json", dest="json_out", help="write the full report as JSON")
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    args.tool = tuple(args.tool)
    if args.unit == "rows" and args.near:
        ap.error("--near applies to per-unit detectors; a rows detector yields its own near flag")
    if args.compare and args.near:
        ap.error("--near is not used with --compare")
    tmpdirs: list[str] = []
    try:
        try:
            path, name = parse_spec(args.detector)
            candidate = load_callable(path, name)
            near = load_callable(*parse_spec(args.near)) if args.near else None
            baseline = resolve_baseline(path, name, args.compare, tmpdirs) if args.compare else None
        except ValueError as exc:
            ap.error(str(exc))
        files = expand(args.paths) if args.paths else discover(args.limit)
        if not files:
            print("no transcripts found", file=sys.stderr)
            return 1
        if baseline is None:
            code, report = run_single(candidate, near, files, args)
        else:
            code, report = run_compare(candidate, baseline, files, args)
    finally:
        for tmp in tmpdirs:
            shutil.rmtree(tmp, ignore_errors=True)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=1, default=str)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
