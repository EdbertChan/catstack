#!/usr/bin/env python3
"""Collect mechanical DORA-for-agents events from local sessions + gh merges + git.

Produces an events JSON list for dora_ai.summarize. Never writes transcript
paths into committed baselines — callers strip events and keep aggregates.

Heuristics (fail-open, approximate):
  - Each recent session → execution_started
  - User approval-ish utterance → plan_approved; next Write/Edit/mutating Bash
    → first_mutating_work
  - token_audit thrash flags (incl. intervention-must-automate) → thrash_signal
    + execution_thrashed; later verify Bash → recovered_verified
  - Git path-churn (≥3 commits overlapping paths in 24h) → execution_rewritten
  - Session Write/Edit paths paired to local git (workspace/cwd +
    CATSTACK_DORA_GIT_ROOTS) → rewrite when churn or thrash+commits
  - gh merged PRs (author=@me) → pr_merged; title Revert → pr_reverted
    (post-merge fail is reported, not gated — fix-forward)

Usage:
    collect_dora_events.py [--hours N] [--out FILE] [--skip-gh] [--skip-sessions]
                           [--skip-git]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import cluster_interventions as ci  # noqa: E402
import git_path_churn as gpc  # noqa: E402
import token_audit  # noqa: E402

APPROVAL_RE = re.compile(
    r"\b(go\s+ahead|ship\s+it|lgtm|approved?|execute|implement\s+it|"
    r"do\s+it|submit\s+(the\s+)?plan|ok,\s*do\s+it|sounds\s+good)\b",
    re.I,
)
MUTATING_TOOLS = {"Write", "Edit", "write", "edit", "Bash", "bash", "Shell", "shell"}
FILE_EDIT_TOOLS = {
    "Write",
    "Edit",
    "write",
    "edit",
    "StrReplace",
    "strreplace",
    "ApplyPatch",
    "apply_patch",
    "ApplyPatch",
}
VERIFY_RE = token_audit.VERIFY_RE
STATUS_BASH_RE = re.compile(
    r"^\s*(git\s+status|git\s+diff|git\s+log|ls\b|pwd\b|echo\b|gh\s+pr\s+list)\b",
    re.I,
)


def _session_id(path: str) -> str:
    return hashlib.sha1(os.path.basename(path).encode()).hexdigest()[:12]


def _iso_from_mtime(path: str) -> str:
    ts = os.path.getmtime(path)
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def discover_sessions_between(
    since: datetime, until: datetime
) -> list[tuple[str, str]]:
    """Return [(kind, path)] with mtime in [since, until]."""
    home = os.path.expanduser("~")
    roots = [
        ("claude", os.path.join(home, ".claude", "projects"), ["find", None, "-iname", "*.jsonl"]),
        ("codex", os.path.join(home, ".codex", "sessions"), ["find", None, "-iname", "rollout-*.jsonl"]),
        (
            "cursor",
            os.path.join(home, ".cursor", "projects"),
            ["find", None, "-path", "*/agent-transcripts/*/*.jsonl"],
        ),
    ]
    since_s = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    until_s = until.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    out: list[tuple[str, str]] = []
    for kind, root, find_tmpl in roots:
        if not os.path.isdir(root):
            continue
        cmd = list(find_tmpl)
        cmd[1] = root
        cmd = cmd + ["-newermt", since_s, "!", "-newermt", until_s]
        try:
            found = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120
            ).stdout.splitlines()
        except (OSError, subprocess.SubprocessError):
            continue
        for path in found:
            path = path.strip()
            if path:
                out.append((kind, path))
    return out


def discover_recent_sessions(hours: float, *, as_of: datetime | None = None) -> list[tuple[str, str]]:
    """Return [(kind, path)] modified within hours ending at as_of (default now)."""
    until = as_of or datetime.now(timezone.utc)
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    since = until - timedelta(hours=hours)
    if as_of is not None:
        return discover_sessions_between(since, until)

    import corpus_scan  # noqa: WPS433

    home = os.path.expanduser("~")
    roots = [
        ("claude", os.path.join(home, ".claude", "projects"), ["find", None, "-iname", "*.jsonl"]),
        ("codex", os.path.join(home, ".codex", "sessions"), ["find", None, "-iname", "rollout-*.jsonl"]),
        (
            "cursor",
            os.path.join(home, ".cursor", "projects"),
            ["find", None, "-path", "*/agent-transcripts/*/*.jsonl"],
        ),
    ]
    out: list[tuple[str, str]] = []
    mmin = corpus_scan._mtime_minutes(hours)
    for kind, root, find_tmpl in roots:
        if not os.path.isdir(root):
            continue
        cmd = list(find_tmpl)
        cmd[1] = root
        cmd = cmd + ["-mmin", f"-{mmin}"]
        try:
            found = subprocess.run(
                cmd, capture_output=True, text=True, timeout=60
            ).stdout.splitlines()
        except (OSError, subprocess.SubprocessError):
            continue
        for path in found:
            path = path.strip()
            if path:
                out.append((kind, path))
    return out


def _iter_tool_calls_claude(path: str) -> list[dict[str, Any]]:
    """Chronological tool calls with approximate timestamps from line order."""
    calls: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8", errors="ignore") as handle:
            for i, line in enumerate(handle):
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(data, dict) or data.get("type") != "assistant":
                    continue
                msg = data.get("message") or {}
                ts = data.get("timestamp")
                for block in msg.get("content") or []:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    name = block.get("name") or ""
                    inp = block.get("input") or {}
                    calls.append(
                        {
                            "index": i,
                            "ts": ts,
                            "name": name,
                            "input": inp,
                        }
                    )
    except OSError:
        return []
    return calls


def _iter_tool_calls_cursor(path: str) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8", errors="ignore") as handle:
            for i, line in enumerate(handle):
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(data, dict):
                    continue
                msg = data.get("message") if isinstance(data.get("message"), dict) else data
                if not isinstance(msg, dict):
                    continue
                for block in msg.get("content") or []:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    calls.append(
                        {
                            "index": i,
                            "ts": data.get("timestamp") or msg.get("timestamp"),
                            "name": block.get("name") or "",
                            "input": block.get("input") or {},
                        }
                    )
    except OSError:
        return []
    return calls


def _is_mutating(call: dict[str, Any]) -> bool:
    name = call.get("name") or ""
    if name not in MUTATING_TOOLS:
        return False
    if name.lower() in ("bash", "shell"):
        cmd = ""
        inp = call.get("input") or {}
        if isinstance(inp, dict):
            cmd = str(inp.get("command") or inp.get("cmd") or "")
        if STATUS_BASH_RE.search(cmd):
            return False
    return True


def _is_verify(call: dict[str, Any]) -> bool:
    name = (call.get("name") or "").lower()
    if name not in ("bash", "shell"):
        return False
    inp = call.get("input") or {}
    cmd = str(inp.get("command") or inp.get("cmd") or "") if isinstance(inp, dict) else ""
    return bool(VERIFY_RE.search(cmd) or token_audit.DIRECT_RUN_RE.search(cmd))


def _thrash_hit(kind: str, path: str) -> bool:
    """Match reflect-on-thrash thresholds when --out flags exist."""
    thresholds = {
        "recurring-failure-signatures": 1,
        "no-verify-edit-streak": 1,
        "frustration-signals": 1,
        "redundant-reads": 3,
        "intervention-must-automate": 1,
    }
    try:
        if kind == "claude":
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
                out_path = tmp.name
            try:
                import io
                from contextlib import redirect_stdout

                with redirect_stdout(io.StringIO()):
                    token_audit.audit_claude(path, out_path=out_path)
                with open(out_path, encoding="utf-8") as handle:
                    report = json.load(handle)
            finally:
                try:
                    os.unlink(out_path)
                except OSError:
                    pass
            for flag in report.get("flags") or []:
                need = thresholds.get(flag.get("name"))
                if need is None:
                    continue
                if flag.get("value") == "yes" and int(flag.get("count") or 0) >= need:
                    return True
            return False
        if kind == "cursor":
            import io
            from contextlib import redirect_stdout

            buf = io.StringIO()
            with redirect_stdout(buf):
                token_audit.audit_cursor(path)
            text = buf.getvalue()
            m = re.search(r"calls with exact repeats: (\d+)", text)
            return bool(m and int(m.group(1)) >= 3)
        if kind == "codex":
            import io
            from contextlib import redirect_stdout

            buf = io.StringIO()
            with redirect_stdout(buf):
                token_audit.audit_codex(path)
            m = re.search(r"tool errors: (\d+)", buf.getvalue())
            return bool(m and int(m.group(1)) >= 3)
    except Exception:
        return False
    return False


def _path_from_tool_input(inp: Any) -> str | None:
    if not isinstance(inp, dict):
        return None
    for key in ("path", "file_path", "filePath", "target_notebook", "target_file"):
        val = inp.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _cwd_from_tool_input(inp: Any) -> str | None:
    if not isinstance(inp, dict):
        return None
    for key in ("cwd", "working_directory", "workingDirectory"):
        val = inp.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _extract_touch_paths(calls: list[dict[str, Any]]) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for call in calls:
        if (call.get("name") or "") not in FILE_EDIT_TOOLS:
            continue
        path = _path_from_tool_input(call.get("input"))
        if path and path not in seen:
            seen.add(path)
            paths.append(path)
    return paths


def _claude_project_cwd(path: str) -> str | None:
    """Decode ~/.claude/projects/<dash-path>/... when that absolute path exists."""
    parts = path.split(os.sep)
    try:
        idx = parts.index("projects")
    except ValueError:
        return None
    if idx + 1 >= len(parts):
        return None
    encoded = parts[idx + 1]
    if not encoded.startswith("-"):
        return None
    segs = encoded.lstrip("-").split("-")
    for end in range(len(segs), 1, -1):
        candidate = "/" + "/".join(segs[:end])
        root = gpc.find_git_root(candidate)
        if root:
            return root
    return None


def _extract_workspace_hints(kind: str, path: str, calls: list[dict[str, Any]]) -> list[str]:
    hints: list[str] = []
    if kind == "claude":
        claude_cwd = _claude_project_cwd(path)
        if claude_cwd:
            hints.append(claude_cwd)
    for call in calls:
        cwd = _cwd_from_tool_input(call.get("input"))
        if cwd:
            hints.append(cwd)
        p = _path_from_tool_input(call.get("input"))
        if p and os.path.isabs(p):
            hints.append(os.path.dirname(p))
    return hints


def events_from_session(kind: str, path: str) -> tuple[list[dict[str, Any]], str | None]:
    """Return (events, resolved_repo_root or None)."""
    eid = _session_id(path)
    mtime = os.path.getmtime(path)
    mtime_iso = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    events: list[dict[str, Any]] = [
        {"kind": "execution_started", "execution_id": eid, "ts": mtime_iso}
    ]

    def stamp(raw_ts: Any, index: int | None) -> str:
        parsed = None
        if isinstance(raw_ts, str):
            text = raw_ts.strip()
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            try:
                parsed = datetime.fromisoformat(text)
            except ValueError:
                parsed = None
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        idx = int(index or 0)
        fake = datetime.fromtimestamp(mtime - max(0, 100_000 - idx), tz=timezone.utc)
        return fake.strftime("%Y-%m-%dT%H:%M:%SZ")

    utterances = ci.extract_user_utterances(path, kind=kind)
    approval_index = None
    for u in utterances:
        if APPROVAL_RE.search(u["text"]):
            approval_index = u.get("index")
            events.append(
                {
                    "kind": "plan_approved",
                    "execution_id": eid,
                    "ts": stamp(u.get("ts"), u.get("index")),
                }
            )
            break

    if kind == "cursor":
        calls = _iter_tool_calls_cursor(path)
    else:
        calls = _iter_tool_calls_claude(path)

    if approval_index is not None:
        for call in calls:
            if call["index"] <= approval_index:
                continue
            if _is_mutating(call):
                events.append(
                    {
                        "kind": "first_mutating_work",
                        "execution_id": eid,
                        "ts": stamp(call.get("ts"), call.get("index")),
                    }
                )
                break

    thrashed = _thrash_hit(kind, path)
    if thrashed:
        thrash_index = calls[0]["index"] if calls else 0
        thrash_ts = stamp(calls[0].get("ts") if calls else None, thrash_index)
        events.append(
            {
                "kind": "thrash_signal",
                "incident_id": eid,
                "execution_id": eid,
                "ts": thrash_ts,
            }
        )
        events.append({"kind": "execution_thrashed", "execution_id": eid, "ts": thrash_ts})
        for call in calls:
            if _is_verify(call):
                events.append(
                    {
                        "kind": "recovered_verified",
                        "incident_id": eid,
                        "ts": stamp(call.get("ts"), call.get("index")),
                    }
                )
                break

    touch_paths = _extract_touch_paths(calls)
    hints = _extract_workspace_hints(kind, path, calls)
    repo = gpc.resolve_repo_root(*hints, *gpc.allowlisted_roots())
    if repo and touch_paths:
        events.extend(
            gpc.pair_session_to_commits(
                repo,
                session_mtime=mtime,
                path_hints=touch_paths,
                execution_id=eid,
                already_thrashed=thrashed,
            )
        )
    return events, repo


def _gh_repo_allowlist() -> list[str]:
    """owner/name repos to pull merged PRs from (includes Invoker)."""
    repos = [
        "EdbertChan/catstack",
        "Neko-Catpital-Labs/Invoker",
        "EdbertChan/Invoker",
    ]
    extra = os.environ.get("CATSTACK_DORA_GH_REPOS") or ""
    for part in extra.split(","):
        part = part.strip()
        if part and "/" in part:
            repos.append(part)
    # Derive from local git roots' remotes.
    for root in gpc.allowlisted_roots():
        try:
            url = subprocess.run(
                ["git", "-C", root, "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            continue
        # git@github.com:Org/Repo.git or https://github.com/Org/Repo.git
        m = re.search(r"github\.com[:/]([^/]+)/([^/.]+)(?:\.git)?$", url)
        if m:
            repos.append(f"{m.group(1)}/{m.group(2)}")
    # Dedupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for r in repos:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def events_from_gh(hours: float, *, as_of: datetime | None = None) -> list[dict[str, Any]]:
    """Merged PRs from allowlisted repos in the window (date-scoped search).

    Uses `gh search ... merged:SINCE..UNTIL` per repo so backfill weeks are not
    stuck at 0 (unlike `gh pr list`, which only returns the newest 100 overall).
    """
    until_dt = as_of or datetime.now(timezone.utc)
    if until_dt.tzinfo is None:
        until_dt = until_dt.replace(tzinfo=timezone.utc)
    since_dt = until_dt - timedelta(hours=hours)
    since_day = since_dt.strftime("%Y-%m-%d")
    until_day = until_dt.strftime("%Y-%m-%d")
    merged_range = f"merged:{since_day}..{until_day}"
    events: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []

    for repo in _gh_repo_allowlist():
        try:
            result = subprocess.run(
                [
                    "gh",
                    "search",
                    "prs",
                    "--repo",
                    repo,
                    "is:merged",
                    merged_range,
                    "--limit",
                    "1000",
                    "--json",
                    "number,title,url,closedAt,repository",
                ],
                capture_output=True,
                text=True,
                timeout=90,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"gh search {repo} failed: {exc}", file=sys.stderr)
            continue
        if result.returncode != 0:
            print(f"gh search {repo}: {result.stderr.strip()}", file=sys.stderr)
            continue
        try:
            found = json.loads(result.stdout or "[]")
        except json.JSONDecodeError:
            found = []
        for row in found:
            row = dict(row)
            row.setdefault("closedAt", row.get("mergedAt"))
            row["repository"] = {"nameWithOwner": repo}
            rows.append(row)
        print(f"gh search {repo} {merged_range}: {len(found)}", file=sys.stderr)

    seen: set[str] = set()
    for row in rows:
        pr_id = str(row.get("url") or f"{row.get('repository')}/{row.get('number')}")
        if pr_id in seen:
            continue
        seen.add(pr_id)
        title = row.get("title") or ""
        ts = row.get("mergedAt") or row.get("closedAt")
        parsed = None
        if isinstance(ts, str):
            text = ts.strip()
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            try:
                parsed = datetime.fromisoformat(text)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                parsed = None
        if parsed is not None and parsed < since_dt:
            continue
        if parsed is not None and parsed > until_dt:
            continue
        auto = title.strip().startswith("[auto]")
        events.append(
            {
                "kind": "pr_merged",
                "pr_id": pr_id,
                "ts": ts,
                "auto": auto,
                "human_asked": not auto,
            }
        )
        if re.search(r"\brevert\b", title, re.I):
            events.append({"kind": "pr_reverted", "pr_id": pr_id, "ts": ts})
    print(f"gh merges in window: {sum(1 for e in events if e['kind']=='pr_merged')}", file=sys.stderr)
    return events


def collect(
    *,
    hours: float,
    skip_gh: bool,
    skip_sessions: bool,
    skip_git: bool = False,
    max_sessions: int = 80,
    as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    session_repos: set[str] = set()
    paired_execution_ids: set[str] = set()
    until = as_of or datetime.now(timezone.utc)
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    if not skip_sessions:
        sessions = discover_recent_sessions(hours, as_of=as_of)
        sessions.sort(key=lambda kp: os.path.getmtime(kp[1]), reverse=True)
        if max_sessions > 0:
            sessions = sessions[:max_sessions]
        print(f"scanning {len(sessions)} session(s)", file=sys.stderr)
        for kind, path in sessions:
            try:
                sess_events, repo = events_from_session(kind, path)
                events.extend(sess_events)
                if repo:
                    session_repos.add(repo)
                for ev in sess_events:
                    if ev.get("kind") == "execution_rewritten" and ev.get("execution_id"):
                        paired_execution_ids.add(str(ev["execution_id"]))
            except Exception as exc:
                print(f"skip session {os.path.basename(path)}: {exc}", file=sys.stderr)
    if not skip_git:
        roots = list(session_repos)
        for root in gpc.allowlisted_roots():
            resolved = gpc.find_git_root(root)
            if resolved and resolved not in roots:
                roots.append(resolved)
        here = gpc.find_git_root(os.path.dirname(os.path.dirname(os.path.dirname(SCRIPTS_DIR))))
        if here and here not in roots:
            roots.append(here)
        print(f"scanning {len(roots)} git root(s) for path-churn", file=sys.stderr)
        since = until - timedelta(hours=hours)
        for root in roots:
            try:
                commits = gpc.list_commits(root, since=since, until=until)
                clusters = gpc.cluster_path_churn(commits)
                git_events: list[dict[str, Any]] = []
                for cluster in clusters:
                    git_events.extend(gpc.events_from_cluster(root, cluster))
            except Exception as exc:
                print(f"skip git {os.path.basename(root)}: {exc}", file=sys.stderr)
                continue
            filtered: list[dict[str, Any]] = []
            skip_ids: set[str] = set()
            for ev in git_events:
                eid = str(ev.get("execution_id") or "")
                if ev.get("kind") == "execution_rewritten" and eid in paired_execution_ids:
                    skip_ids.add(eid)
            for ev in git_events:
                eid = str(ev.get("execution_id") or "")
                if eid in skip_ids:
                    continue
                filtered.append(ev)
            events.extend(filtered)
    if not skip_gh:
        events.extend(events_from_gh(hours, as_of=as_of))
    return events


def public_summary(summary: dict[str, Any], *, window_days: float, hours: float) -> dict[str, Any]:
    """Drop raw sample lists — safe to commit."""
    lead = summary["lead_pickup"]
    mttr = summary["mttr"]
    return {
        "window_days": window_days,
        "hours_scanned": hours,
        "lead_pickup": {
            "median_seconds": lead["median_seconds"],
            "sample_count": len(lead.get("samples") or []),
            "elite": lead["elite"],
            "threshold_seconds": lead["threshold_seconds"],
        },
        "deploy_frequency": {
            "per_day": summary["deploy_frequency"]["per_day"],
            "merged": summary["deploy_frequency"]["merged"],
            "auto": summary["deploy_frequency"]["auto"],
            "human_asked": summary["deploy_frequency"]["human_asked"],
            "human_only": summary["deploy_frequency"]["human_only"],
            "elite": summary["deploy_frequency"]["elite"],
            "threshold_per_day": summary["deploy_frequency"]["threshold_per_day"],
        },
        "mttr": {
            "median_seconds": mttr["median_seconds"],
            "sample_count": len(mttr.get("samples") or []),
            "elite": mttr["elite"],
            "threshold_seconds": mttr["threshold_seconds"],
        },
        "rework_rate": {
            "rate": summary["rework_rate"]["rate"],
            "started": summary["rework_rate"]["started"],
            "failed": summary["rework_rate"]["failed"],
            "elite": summary["rework_rate"]["elite"],
            "threshold": summary["rework_rate"]["threshold"],
        },
        "post_merge_fail_rate": {
            "rate": summary["post_merge_fail_rate"]["rate"],
            "merged": summary["post_merge_fail_rate"]["merged"],
            "failed": summary["post_merge_fail_rate"]["failed"],
            "elite": summary["post_merge_fail_rate"]["elite"],
            "threshold": summary["post_merge_fail_rate"]["threshold"],
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hours", type=float, default=168.0)
    ap.add_argument("--out", default=None, help="write events JSON (local/cache only)")
    ap.add_argument("--skip-gh", action="store_true")
    ap.add_argument("--skip-sessions", action="store_true")
    ap.add_argument("--skip-git", action="store_true")
    ap.add_argument("--max-sessions", type=int, default=80)
    args = ap.parse_args(argv)
    events = collect(
        hours=args.hours,
        skip_gh=args.skip_gh,
        skip_sessions=args.skip_sessions,
        skip_git=args.skip_git,
        max_sessions=args.max_sessions,
    )
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(events, handle, indent=2)
            handle.write("\n")
        print(f"wrote {len(events)} events -> {args.out}", file=sys.stderr)
    else:
        print(json.dumps(events, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
