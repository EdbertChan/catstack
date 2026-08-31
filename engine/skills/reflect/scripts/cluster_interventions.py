#!/usr/bin/env python3
"""Cluster repeated user interventions across Claude / Cursor / Codex transcripts.

Mechanical only — no LLM. Normalizes short user pokes ("make pr", "open a pr"),
groups them across sessions, and splits each cluster into yes/no circumstance
buckets (when the user wanted the action vs when they did not).

Usage:
    cluster_interventions.py [--hours N] [--paths FILE ...] [--out FILE]

Never writes transcripts into git. Output is a ranked queue of clusters with
hashes, counts, short quotes, and paths.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from typing import Any

import transcript_provenance

# Phrases that look like the user poking the agent to do a recurring chore.
# Keep patterns tight: whole-ish utterance, not substring hits inside tool noise.
INTERVENTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("make_pr", re.compile(
        r"\b(make|open|create|draft|publish)\s+(a\s+|the\s+)?(pr|pull\s*request)\b",
        re.I,
    )),
    ("commit_push", re.compile(r"\b(commit|push)\b.*\b(and\s+)?(push|commit)\b|\bcommit\s+and\s+push\b", re.I)),
    ("reflect", re.compile(r"\b/?reflect\b", re.I)),
    ("eli5", re.compile(r"\beli\s*5\b|\bexplain\s+like\s+i'?m\s+5\b", re.I)),
    ("automate_me", re.compile(r"\bautomate\s+me\b|\bcapture\s+(how|this)\b", re.I)),
    ("try_again", re.compile(r"\b(try\s+again|do\s+it\s+again|same\s+thing)\b", re.I)),
    ("just_do_it", re.compile(r"\b(just\s+do\s+it|why\s+don'?t\s+you\s+just|can\s+you\s+(just\s+)?(do|run|start)\b)", re.I)),
]

NEGATIVE_CIRCUMSTANCE = re.compile(
    r"\b(don'?t|do\s+not|not\s+yet|wait|hold\s+off|plan\s+mode|don'?t\s+(make|open|create)|"
    r"no\s+pr|skip\s+(the\s+)?pr|wip|don'?t\s+commit)\b",
    re.I,
)
POSITIVE_CIRCUMSTANCE = re.compile(
    r"\b(go\s+ahead|ship\s+it|ready|tests?\s+pass|done|finish|open\s+it|"
    r"make\s+the\s+pr|create\s+the\s+pr)\b",
    re.I,
)

def sniff_kind(path: str) -> str:
    base = os.path.basename(path)
    if base.startswith("rollout-"):
        return "codex"
    if "/agent-transcripts/" in path.replace("\\", "/"):
        return "cursor"
    return "claude"


def extract_user_utterances(
    path: str, kind: str | None = None
) -> list[transcript_provenance.HumanUtterance]:
    """Return automation-safe, typed direct-human utterances only."""
    harness = kind or sniff_kind(path)
    if harness not in ("claude", "codex", "cursor"):
        return []
    return transcript_provenance.direct_human_utterances(path, harness)


def normalize_phrase(text: str) -> str | None:
    """Map an utterance to a cluster key, or None if it is not an intervention."""
    compact = " ".join(text.split())
    if len(compact) > 280:
        # Long messages are usually content, not a poke — still match short patterns
        # but prefer the first matching pattern on the first ~280 chars.
        compact = compact[:280]
    for name, pattern in INTERVENTION_PATTERNS:
        if pattern.search(compact):
            return name
    return None


def circumstance_bucket(text: str, neighbors: list[str] | None = None) -> str:
    """yes = user wanted the action; no = user did not; unclear = insufficient."""
    blob = text
    if neighbors:
        blob = " ".join(neighbors + [text])
    if NEGATIVE_CIRCUMSTANCE.search(blob):
        return "no"
    if POSITIVE_CIRCUMSTANCE.search(blob) or normalize_phrase(text):
        # Bare "make pr" without negation is a yes circumstance for the poke itself.
        if NEGATIVE_CIRCUMSTANCE.search(text):
            return "no"
        return "yes"
    return "unclear"


def cluster_hash(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def cluster_utterances(
    utterances: list[transcript_provenance.HumanUtterance],
    *,
    min_sessions: int = 2,
    min_utterances: int = 3,
) -> list[dict[str, Any]]:
    """Group intervention utterances into ranked clusters."""
    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for u in utterances:
        if not u.can_trigger_intervention:
            continue
        key = normalize_phrase(u.text)
        if not key:
            continue
        bucket = circumstance_bucket(u.text)
        row = {
            "cluster_key": key,
            "circumstance": bucket,
            "quote": " ".join(u.text.split())[:120],
            "path": u.path,
            "harness": u.harness,
            "lineage_id": u.lineage_id,
        }
        by_key[key].append(row)

    clusters: list[dict[str, Any]] = []
    for key, rows in by_key.items():
        sessions = {(r["harness"], r["lineage_id"]) for r in rows}
        yes = [r for r in rows if r["circumstance"] == "yes"]
        no = [r for r in rows if r["circumstance"] == "no"]
        unclear = [r for r in rows if r["circumstance"] == "unclear"]
        complete = bool(yes) and bool(no)
        high = len(sessions) >= min_sessions or len(rows) >= min_utterances
        clusters.append(
            {
                "cluster_key": key,
                "hash": cluster_hash(key),
                "utterance_count": len(rows),
                "session_count": len(sessions),
                "high_confidence": high,
                "circumstance_complete": complete,
                "yes_count": len(yes),
                "no_count": len(no),
                "unclear_count": len(unclear),
                "quotes": [r["quote"] for r in rows[:5]],
                "paths": sorted({r["path"] for r in rows})[:20],
                "yes_examples": [r["quote"] for r in yes[:3]],
                "no_examples": [r["quote"] for r in no[:3]],
            }
        )
    clusters.sort(key=lambda c: (-c["utterance_count"], -c["session_count"], c["cluster_key"]))
    return clusters


def scan_paths(paths: list[str]) -> list[dict[str, Any]]:
    utterances: list[transcript_provenance.HumanUtterance] = []
    for path in paths:
        utterances.extend(extract_user_utterances(path))
    return cluster_utterances(utterances)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hours", type=float, default=168.0, help="unused when --paths given")
    ap.add_argument("--paths", nargs="*", default=[], help="explicit transcript paths")
    ap.add_argument("--out", default=None, help="write JSON clusters here")
    ap.add_argument("--min-sessions", type=int, default=2)
    ap.add_argument("--min-utterances", type=int, default=3)
    args = ap.parse_args(argv)

    paths = list(args.paths)
    if not paths:
        # Discover via corpus_scan with a broad intervention pattern.
        scripts_dir = os.path.dirname(os.path.abspath(__file__))
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        import corpus_scan  # noqa: WPS433

        pattern = r"make (a )?pr|open (a )?pr|commit and push|/reflect|eli ?5|automate me|try again"
        for kind, path, _host in corpus_scan.discover_local(pattern, args.hours):
            paths.append(path)

    utterances: list[transcript_provenance.HumanUtterance] = []
    for path in paths:
        utterances.extend(extract_user_utterances(path))
    clusters = cluster_utterances(
        utterances,
        min_sessions=args.min_sessions,
        min_utterances=args.min_utterances,
    )
    payload = {"clusters": clusters, "paths_scanned": len(paths), "utterances": len(utterances)}
    text = json.dumps(payload, indent=2)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text)
        print(f"wrote {len(clusters)} cluster(s) -> {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
