#!/usr/bin/env python3
"""Mine local git history for fix-forward path churn (rewrite clusters).

A cluster is ≥MIN_COMMITS commits within CLUSTER_WINDOW_HOURS that share
≥MIN_OVERLAP_PATHS overlapping paths, or ≥MIN_COMMITS commits all touching
the same single path.

Emits execution_rewritten (+ thrash_signal) events for dora_ai.rework_rate.
Never writes absolute paths into committed baselines — callers keep aggregates.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Any

MIN_COMMITS = 3
CLUSTER_WINDOW_HOURS = 24.0
MIN_OVERLAP_PATHS = 2
AGENT_TRAILER_RE = re.compile(
    r"(?im)^Co-Authored-By:\s*(Claude|Cursor|Codex|GitHub\s+Copilot)\b"
)
VERIFY_MSG_RE = re.compile(
    r"(?i)\b(test|tests|verify|ci\s+pass|green|fix(?:es|ed)?\s+and\s+verif)",
)


def allowlisted_roots() -> list[str]:
    raw = os.environ.get("CATSTACK_DORA_GIT_ROOTS") or ""
    roots: list[str] = []
    for part in raw.split(":"):
        part = part.strip()
        if not part:
            continue
        path = os.path.abspath(os.path.expanduser(part))
        if os.path.isdir(os.path.join(path, ".git")) or os.path.isdir(path):
            roots.append(path)
    return roots


def find_git_root(start: str | None) -> str | None:
    if not start:
        return None
    path = os.path.abspath(os.path.expanduser(start))
    if os.path.isfile(path):
        path = os.path.dirname(path)
    cur = path
    while True:
        if os.path.isdir(os.path.join(cur, ".git")) or os.path.isfile(
            os.path.join(cur, ".git")
        ):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return None


def resolve_repo_root(*candidates: str | None) -> str | None:
    for cand in candidates:
        root = find_git_root(cand)
        if root:
            return root
    for root in allowlisted_roots():
        resolved = find_git_root(root)
        if resolved:
            return resolved
    return None


def _run_git(repo: str, args: list[str], *, timeout: int = 60) -> str:
    result = subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        return ""
    return result.stdout or ""


def _parse_iso(ts: str) -> datetime | None:
    text = ts.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def list_commits(
    repo: str,
    *,
    since: datetime,
    until: datetime | None = None,
    path_hints: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Return commits oldest-first with relative paths touched."""
    args = [
        "log",
        "--reverse",
        "--max-count=400",
        f"--since={_iso(since)}",
        "--name-only",
        "--pretty=format:>>>COMMIT %H|%cI|%s",
    ]
    if until is not None:
        args.insert(3, f"--until={_iso(until)}")
    rels: list[str] = []
    if path_hints:
        for hint in path_hints:
            hint = hint.strip()
            if not hint:
                continue
            if os.path.isabs(hint):
                try:
                    rel = os.path.relpath(hint, repo)
                except ValueError:
                    continue
                if rel.startswith(".."):
                    continue
                rels.append(rel)
            else:
                rels.append(hint.lstrip("./"))
        if rels:
            args.append("--")
            args.extend(sorted(set(rels))[:80])
    out = _run_git(repo, args)
    if not out.strip():
        return []

    # Trailers (Co-Authored-By) need a second pass for agent detection.
    commits: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in out.splitlines():
        if line.startswith(">>>COMMIT "):
            if current is not None:
                commits.append(current)
            payload = line[len(">>>COMMIT ") :]
            parts = payload.split("|", 2)
            if len(parts) < 3:
                current = None
                continue
            sha, ciso, subject = parts[0], parts[1], parts[2]
            dt = _parse_iso(ciso)
            if dt is None:
                current = None
                continue
            current = {
                "sha": sha,
                "ts": dt,
                "subject": subject,
                "paths": [],
                "agent": False,
                "verify_msg": bool(VERIFY_MSG_RE.search(subject)),
            }
            continue
        if current is None:
            continue
        path = line.strip()
        if path:
            current["paths"].append(path)
    if current is not None:
        commits.append(current)
    # Agent trailer detection skipped for speed (prefer_agent falls back to all).
    return commits


def cluster_path_churn(
    commits: list[dict[str, Any]],
    *,
    min_commits: int = MIN_COMMITS,
    window_hours: float = CLUSTER_WINDOW_HOURS,
    min_overlap_paths: int = MIN_OVERLAP_PATHS,
) -> list[list[dict[str, Any]]]:
    """Greedy clusters: walk oldest→newest, grow while within window + overlap."""
    if not commits:
        return []
    ordered = sorted(commits, key=lambda c: c["ts"])
    window = timedelta(hours=window_hours)
    clusters: list[list[dict[str, Any]]] = []
    used: set[str] = set()

    for i, start in enumerate(ordered):
        if start["sha"] in used:
            continue
        cluster = [start]
        paths = set(start["paths"])
        end_ts = start["ts"] + window
        for nxt in ordered[i + 1 :]:
            if nxt["ts"] > end_ts:
                break
            if nxt["sha"] in used:
                continue
            nxt_paths = set(nxt["paths"])
            overlap = paths & nxt_paths
            same_single = bool(paths) and paths == nxt_paths and len(paths) == 1
            if len(overlap) >= min_overlap_paths or same_single or (
                len(paths) == 1 and paths <= nxt_paths
            ):
                cluster.append(nxt)
                paths |= nxt_paths
        if len(cluster) >= min_commits:
            # Also accept ≥min_commits all touching one shared path.
            shared_any = None
            for p in paths:
                if sum(1 for c in cluster if p in c["paths"]) >= min_commits:
                    shared_any = p
                    break
            overlap_ok = False
            # Re-check: every consecutive pair or overall intersection size
            if shared_any is not None:
                overlap_ok = True
            else:
                # Require at least min_overlap among commits pairwise via common set
                common = set(cluster[0]["paths"])
                for c in cluster[1:]:
                    common &= set(c["paths"])
                if len(common) >= min_overlap_paths or (
                    len(common) >= 1 and len(cluster) >= min_commits
                ):
                    overlap_ok = True
            if overlap_ok:
                for c in cluster:
                    used.add(c["sha"])
                clusters.append(cluster)
    return clusters


def _cluster_execution_id(repo: str, cluster: list[dict[str, Any]]) -> str:
    repo_name = os.path.basename(os.path.abspath(repo).rstrip("/")) or "repo"
    first = cluster[0]["sha"]
    return hashlib.sha1(f"{repo_name}:{first}".encode()).hexdigest()[:12]


def events_from_cluster(
    repo: str, cluster: list[dict[str, Any]], *, execution_id: str | None = None
) -> list[dict[str, Any]]:
    eid = execution_id or _cluster_execution_id(repo, cluster)
    first_ts = _iso(cluster[0]["ts"])
    last_ts = _iso(cluster[-1]["ts"])
    rel_paths = sorted({p for c in cluster for p in c["paths"]})[:40]
    events: list[dict[str, Any]] = [
        {
            "kind": "execution_started",
            "execution_id": eid,
            "ts": first_ts,
            "source": "git_path_churn",
            "repo": os.path.basename(os.path.abspath(repo).rstrip("/")),
            "paths": rel_paths,
            "commit_count": len(cluster),
        },
        {
            "kind": "thrash_signal",
            "incident_id": eid,
            "execution_id": eid,
            "ts": first_ts,
            "source": "git_path_churn",
        },
        {
            "kind": "execution_rewritten",
            "execution_id": eid,
            "ts": last_ts,
            "source": "git_path_churn",
            "commit_count": len(cluster),
        },
    ]
    for c in reversed(cluster):
        if c.get("verify_msg"):
            events.append(
                {
                    "kind": "recovered_verified",
                    "incident_id": eid,
                    "ts": _iso(c["ts"]),
                    "source": "git_path_churn",
                }
            )
            break
    return events


def events_from_git(
    repo_root: str,
    *,
    since_hours: float,
    path_hints: list[str] | None = None,
    until: datetime | None = None,
    prefer_agent: bool = True,
) -> list[dict[str, Any]]:
    """Mine one repo for path-churn rewrite clusters."""
    root = find_git_root(repo_root)
    if not root:
        return []
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    commits = list_commits(root, since=since, until=until, path_hints=path_hints)
    if prefer_agent:
        agent = [c for c in commits if c.get("agent")]
        # Prefer agent commits but fall back to all if agent set too small.
        pool = agent if len(agent) >= MIN_COMMITS else commits
    else:
        pool = commits
    events: list[dict[str, Any]] = []
    for cluster in cluster_path_churn(pool):
        events.extend(events_from_cluster(root, cluster))
    return events


def pair_session_to_commits(
    repo_root: str,
    *,
    session_mtime: float,
    path_hints: list[str],
    execution_id: str,
    already_thrashed: bool,
    lookback_hours: float = 6.0,
    lookforward_hours: float = 24.0,
) -> list[dict[str, Any]]:
    """Join a session to overlapping-path commits; emit rewrite on churn or thrash."""
    root = find_git_root(repo_root)
    if not root or not path_hints:
        return []
    mtime_dt = datetime.fromtimestamp(session_mtime, tz=timezone.utc)
    since = mtime_dt - timedelta(hours=lookback_hours)
    until = mtime_dt + timedelta(hours=lookforward_hours)
    commits = list_commits(root, since=since, until=until, path_hints=path_hints)
    if not commits:
        if already_thrashed:
            # Session thrash alone already emits execution_thrashed; no extra
            # rewrite without commit evidence.
            return []
        return []

    clusters = cluster_path_churn(commits)
    events: list[dict[str, Any]] = []
    if clusters:
        # Attach first cluster to this session id (no double start).
        cluster = clusters[0]
        last_ts = _iso(cluster[-1]["ts"])
        events.append(
            {
                "kind": "execution_rewritten",
                "execution_id": execution_id,
                "ts": last_ts,
                "source": "session_git_pair",
                "commit_count": len(cluster),
                "repo": os.path.basename(os.path.abspath(root).rstrip("/")),
                "paths": sorted({p for c in cluster for p in c["paths"]})[:40],
            }
        )
        if not already_thrashed:
            events.insert(
                0,
                {
                    "kind": "thrash_signal",
                    "incident_id": execution_id,
                    "execution_id": execution_id,
                    "ts": _iso(cluster[0]["ts"]),
                    "source": "session_git_pair",
                },
            )
        for c in reversed(cluster):
            if c.get("verify_msg"):
                events.append(
                    {
                        "kind": "recovered_verified",
                        "incident_id": execution_id,
                        "ts": _iso(c["ts"]),
                        "source": "session_git_pair",
                    }
                )
                break
        return events

    # Below cluster threshold but session thrashed and ≥2 commits on same paths
    # → still mark rewritten (fix-forward patching after thrash).
    if already_thrashed and len(commits) >= 2:
        events.append(
            {
                "kind": "execution_rewritten",
                "execution_id": execution_id,
                "ts": _iso(commits[-1]["ts"]),
                "source": "session_git_pair",
                "commit_count": len(commits),
                "repo": os.path.basename(os.path.abspath(root).rstrip("/")),
            }
        )
    return events
