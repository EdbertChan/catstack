#!/usr/bin/env python3
"""Aggregate A/B skill-token runs from a registry.json."""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from codex_session_tokens import score_parent



def find_parent_session(markers: list[str], sessions_root: Path) -> Path | None:
    hits: list[Path] = []
    for path in sessions_root.rglob("rollout-*.jsonl"):
        try:
            head = path.read_bytes()[:3_000_000]
        except OSError:
            continue
        if markers and all(m.encode() for m in markers if m) and all(
            (m.encode() in head) for m in markers if m
        ):
            hits.append(path)
    if not hits and markers:
        for path in sessions_root.rglob("rollout-*.jsonl"):
            try:
                head = path.read_bytes()[:3_000_000]
            except OSError:
                continue
            if any((m.encode() in head) for m in markers if m):
                hits.append(path)
    if not hits:
        return None
    hits.sort(key=lambda p: p.stat().st_size, reverse=True)
    return hits[0]


def summarize(vals: list[int]) -> dict:
    if not vals:
        return {"n": 0}
    return {
        "n": len(vals),
        "min": min(vals),
        "max": max(vals),
        "mean": round(statistics.mean(vals), 1),
        "median": statistics.median(vals),
        "stdev": round(statistics.stdev(vals), 1) if len(vals) > 1 else 0.0,
    }


def score_entry(entry: dict, sessions_root: Path) -> dict:
    arm = entry["arm"]
    rep = entry["rep"]
    workflow_id = entry.get("workflow_id")
    name_prefix = entry.get("name_prefix")
    markers = [m for m in [workflow_id, name_prefix] if m]
    parent = None
    if workflow_id:
        exact = []
        needle = workflow_id.encode()
        for path in sessions_root.rglob("rollout-*.jsonl"):
            try:
                if needle in path.read_bytes()[:3_000_000]:
                    exact.append(path)
            except OSError:
                pass
        if exact:
            exact.sort(key=lambda p: p.stat().st_size, reverse=True)
            parent = exact[0]
    if parent is None:
        parent = find_parent_session(markers, sessions_root)
    base = {
        "arm": arm,
        "rep": rep,
        "workflow_id": workflow_id,
        "parent_session": None,
        "inclusive_total_tokens": None,
        "inclusive_uncached_plus_output": None,
        "spawn_agent_calls": 0,
        "capture_helper": None,
        "children": [],
    }
    if parent is None:
        return base
    scored = score_parent(parent, sessions_root)
    base.update(scored)
    return base


def build_aggregate(registry: dict, sessions_root: Path) -> dict:
    runs = []
    for arm, meta in (registry.get("original") or {}).items():
        runs.append(
            score_entry(
                {
                    "arm": arm,
                    "rep": meta.get("rep", "r1"),
                    "workflow_id": meta.get("workflow_id"),
                    "name_prefix": meta.get("name_prefix"),
                },
                sessions_root,
            )
        )
    for plan in registry.get("plans") or []:
        wf = None
        for sub in registry.get("submissions") or []:
            if sub.get("arm") == plan["arm"] and sub.get("rep") == plan["rep"]:
                wf = sub.get("workflow_id")
        runs.append(
            score_entry(
                {
                    "arm": plan["arm"],
                    "rep": plan["rep"],
                    "workflow_id": wf,
                    "name_prefix": plan.get("name_prefix"),
                },
                sessions_root,
            )
        )
    for sub in registry.get("submissions") or []:
        if any(r["arm"] == sub["arm"] and r["rep"] == sub["rep"] for r in runs):
            continue
        runs.append(
            score_entry(
                {
                    "arm": sub["arm"],
                    "rep": sub["rep"],
                    "workflow_id": sub.get("workflow_id"),
                    "name_prefix": sub.get("name_prefix"),
                },
                sessions_root,
            )
        )

    by_arm: dict[str, list] = {}
    for run in runs:
        by_arm.setdefault(run["arm"], []).append(run)

    agg: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runs": runs,
        "by_arm": {},
        "pass_gate": None,
    }
    for arm, items in by_arm.items():
        totals = [r["inclusive_total_tokens"] for r in items if r.get("inclusive_total_tokens") is not None]
        uncs = [
            r["inclusive_uncached_plus_output"]
            for r in items
            if r.get("inclusive_uncached_plus_output") is not None
        ]
        helpers = [r["capture_helper"] for r in items if r.get("capture_helper") is not None]
        agg["by_arm"][arm] = {
            "inclusive_total_tokens": summarize(totals),
            "inclusive_uncached_plus_output": summarize(uncs),
            "capture_helper_rate": (sum(1 for h in helpers if h) / len(helpers)) if helpers else None,
            "reps_scored": [r["rep"] for r in items if r.get("inclusive_total_tokens") is not None],
            "reps_missing": [r["rep"] for r in items if r.get("inclusive_total_tokens") is None],
        }

    a = agg["by_arm"].get("A", {}).get("inclusive_total_tokens", {})
    b = agg["by_arm"].get("B", {}).get("inclusive_total_tokens", {})
    if a.get("n") and b.get("n"):
        agg["delta_median_A_minus_B"] = a["median"] - b["median"]
        agg["delta_mean_A_minus_B"] = a["mean"] - b["mean"]
        agg["pass_gate"] = bool(b["median"] < a["median"])
    return agg


def write_report(agg: dict, out_dir: Path) -> Path:
    lines = [
        "# skill A/B token gate",
        "",
        f"Generated: {agg['generated_at']}",
        "",
        f"Pass gate (median B < median A): **{agg.get('pass_gate')}**",
        "",
        "## Per-arm inclusive tokens",
        "",
        "| arm | n | min | median | mean | max | stdev | capture_helper_rate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in sorted(agg["by_arm"]):
        stats = agg["by_arm"][arm]["inclusive_total_tokens"]
        if not stats.get("n"):
            lines.append(f"| {arm} | 0 | — | — | — | — | — | — |")
            continue
        rate = agg["by_arm"][arm]["capture_helper_rate"]
        lines.append(
            f"| {arm} | {stats['n']} | {stats['min']:,} | {stats['median']:,} | "
            f"{stats['mean']:,} | {stats['max']:,} | {stats['stdev']:,} | {rate} |"
        )
    lines.append("")
    if "delta_median_A_minus_B" in agg:
        lines.append(f"- delta median A−B: **{agg['delta_median_A_minus_B']:,}**")
        lines.append(f"- delta mean A−B: **{agg['delta_mean_A_minus_B']:,}**")
    lines.append("")
    lines.append("## Runs")
    lines.append("")
    for run in agg["runs"]:
        lines.append(
            f"- {run['arm']}/{run['rep']} wf={run.get('workflow_id')} "
            f"inclusive={run.get('inclusive_total_tokens')} "
            f"spawn={run.get('spawn_agent_calls')} helper={run.get('capture_helper')}"
        )
    path = out_dir / "REPORT.md"
    path.write_text("\n".join(lines) + "\n")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--sessions-root",
        type=Path,
        default=Path.home() / ".codex" / "sessions",
    )
    args = parser.parse_args()
    registry = json.loads(args.registry.read_text())
    args.out.mkdir(parents=True, exist_ok=True)
    agg = build_aggregate(registry, args.sessions_root)
    (args.out / "aggregate.json").write_text(json.dumps(agg, indent=2) + "\n")
    (args.out / "registry.json").write_text(json.dumps(registry, indent=2) + "\n")
    write_report(agg, args.out)
    print(json.dumps({"pass_gate": agg.get("pass_gate"), "out": str(args.out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
