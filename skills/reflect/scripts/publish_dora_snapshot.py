#!/usr/bin/env python3
"""Capture DORA snapshot, update history/charts/report, open a PR (never merge).

Usage:
    python3 skills/reflect/scripts/publish_dora_snapshot.py --dry-run
    python3 skills/reflect/scripts/publish_dora_snapshot.py --fixture-measurement PATH
    python3 skills/reflect/scripts/publish_dora_snapshot.py --repo /path/to/catstack

Safety: aggregates only; never merges; baseline updates only when --check-update passes.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DEFAULT = os.path.dirname(os.path.dirname(os.path.dirname(SCRIPTS_DIR)))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import capture_dora_baseline  # noqa: E402
import dora_history  # noqa: E402
import render_dora_charts  # noqa: E402
import render_dora_report  # noqa: E402

# Import check helpers without executing main.
REPO_SCRIPTS = os.path.join(REPO_DEFAULT, "scripts")
if REPO_SCRIPTS not in sys.path:
    sys.path.insert(0, REPO_SCRIPTS)
import check_dora_baseline as cdb  # noqa: E402


def _baselines_dir(repo: str) -> str:
    return os.path.join(repo, "skills", "reflect", "baselines")


def _run(
    cmd: list[str],
    *,
    cwd: str,
    dry_run: bool,
    allow_gh: bool,
) -> subprocess.CompletedProcess[str] | None:
    if dry_run and (cmd[0] == "gh" or (cmd[0] == "git" and cmd[1] in ("push",))):
        print(f"dry-run skip: {' '.join(cmd)}", file=sys.stderr)
        return None
    if not allow_gh and cmd[0] == "gh":
        raise RuntimeError(f"gh blocked: {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)


def apply_snapshot(
    repo: str,
    measurement: dict[str, Any],
    *,
    replace_same_week: bool = True,
) -> dict[str, Any]:
    """Write history/charts/report; update baseline only if equal-or-better.

    Returns summary dict for logging / tests.
    """
    bdir = _baselines_dir(repo)
    os.makedirs(bdir, exist_ok=True)
    baseline_path = os.path.join(bdir, "dora-ai.json")
    history_path = os.path.join(bdir, "dora-ai-history.json")
    charts_dir = os.path.join(bdir, "charts")
    report_path = os.path.join(bdir, "dora-ai-report.md")

    history = dora_history.load_history(history_path)
    point = dora_history.snapshot_from_measurement(measurement)
    history, hist_changed = dora_history.append_point(
        history, point, replace_same_week=replace_same_week
    )
    dora_history.save_history(history_path, history)

    chart_paths = render_dora_charts.render_all(history, charts_dir)
    report_text = render_dora_report.render_report(measurement)
    with open(report_path, "w", encoding="utf-8") as handle:
        handle.write(report_text)

    baseline_updated = False
    if os.path.isfile(baseline_path):
        with open(baseline_path, encoding="utf-8") as handle:
            baseline = json.load(handle)
        problems = cdb.can_update_baseline(baseline, measurement)
        if not problems:
            with open(baseline_path, "w", encoding="utf-8") as handle:
                json.dump(measurement, handle, indent=2)
                handle.write("\n")
            baseline_updated = True
        else:
            print("baseline not updated (regression vs committed):", file=sys.stderr)
            for p in problems:
                print(f"  - {p}", file=sys.stderr)
    else:
        with open(baseline_path, "w", encoding="utf-8") as handle:
            json.dump(measurement, handle, indent=2)
            handle.write("\n")
        baseline_updated = True

    return {
        "history_changed": hist_changed,
        "baseline_updated": baseline_updated,
        "chart_paths": chart_paths,
        "report_path": report_path,
        "history_path": history_path,
        "baseline_path": baseline_path,
        "files": [
            history_path,
            report_path,
            baseline_path,
            *chart_paths,
        ],
    }


def publish(
    *,
    repo: str,
    dry_run: bool,
    max_sessions: int,
    fixture_measurement: str | None,
    base_branch: str,
    allow_gh: bool,
) -> int:
    if fixture_measurement:
        with open(fixture_measurement, encoding="utf-8") as handle:
            measurement = json.load(handle)
        print(f"using fixture measurement {fixture_measurement}", file=sys.stderr)
    else:
        # Capture into memory then apply (do not write capture's default path first).
        old_cwd = os.getcwd()
        try:
            os.chdir(repo)
            measurement = capture_dora_baseline.capture(max_sessions=max_sessions)
        finally:
            os.chdir(old_cwd)

    result = apply_snapshot(repo, measurement)
    changed_files = []
    for path in result["files"]:
        if os.path.isfile(path):
            # relative for git add
            rel = os.path.relpath(path, repo)
            changed_files.append(rel)

    # Also refresh README sparkline is already under charts/; README markdown may
    # already reference it — no rewrite required unless missing block (caller docs).

    print(
        json.dumps(
            {
                "history_changed": result["history_changed"],
                "baseline_updated": result["baseline_updated"],
                "files": changed_files,
            },
            indent=2,
        ),
        file=sys.stderr,
    )

    if dry_run:
        print("dry-run: would open PR with files:", file=sys.stderr)
        for f in changed_files:
            print(f"  - {f}", file=sys.stderr)
        return 0

    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    branch = f"dora/snapshot-{day}"
    # Ensure we're in a git repo
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if status.returncode != 0:
        print("not a git repo", file=sys.stderr)
        return 1

    subprocess.run(["git", "checkout", "-B", branch], cwd=repo, check=False)
    subprocess.run(["git", "add", *changed_files], cwd=repo, check=False)
    # Skip if nothing staged
    diff = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=repo, check=False
    )
    if diff.returncode == 0:
        print("nothing to commit", file=sys.stderr)
        return 0

    msg = (
        f"[dora-snapshot] Weekly DORA measurement {day}\n\n"
        f"baseline_updated={result['baseline_updated']}\n"
    )
    subprocess.run(
        ["git", "commit", "-m", msg],
        cwd=repo,
        check=False,
    )
    push = _run(
        ["git", "push", "-u", "origin", "HEAD"],
        cwd=repo,
        dry_run=False,
        allow_gh=True,
    )
    if push is not None and push.returncode != 0:
        print(push.stderr, file=sys.stderr)
        return 1

    body = f"""## Summary

Weekly DORA-for-agents snapshot. History and charts updated. Baseline updated: **{result['baseline_updated']}**.

## Review Claim

Approve committing this week's aggregate DORA measurement and chart refresh.

## Review Lane

proof

## Review Unit

reflect-dora-snapshot

## Safety Invariant

Aggregates only — no transcript paths. Job never merges. Baseline only updates when equal-or-better.

## Non-goals

Does not merge this PR automatically.

## Test Plan

<details>
<summary>Test Plan</summary>

- [x] publish_dora_snapshot produced history/charts/report
- [ ] Review SVG trend direction on the report page

</details>

## Revert Plan

<details>
<summary>Revert Plan</summary>

- Safe to revert? Yes
- Revert command: close PR or `git revert`
- Data migration? No

</details>
"""
    pr = _run(
        [
            "gh",
            "pr",
            "create",
            "--base",
            base_branch,
            "--title",
            f"[dora-snapshot] Weekly DORA measurement {day}",
            "--body",
            body,
        ],
        cwd=repo,
        dry_run=False,
        allow_gh=allow_gh,
    )
    if pr is None:
        return 0
    if pr.returncode != 0:
        print(pr.stderr, file=sys.stderr)
        return 1
    print(pr.stdout)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=REPO_DEFAULT)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-sessions", type=int, default=40)
    ap.add_argument("--fixture-measurement", default=None)
    ap.add_argument("--base-branch", default="main")
    ap.add_argument(
        "--allow-gh",
        action="store_true",
        default=True,
        help="allow gh pr create (default true; tests pass --no-allow-gh)",
    )
    ap.add_argument("--no-allow-gh", action="store_true")
    args = ap.parse_args(argv)
    allow_gh = not args.no_allow_gh
    return publish(
        repo=os.path.abspath(args.repo),
        dry_run=args.dry_run,
        max_sessions=args.max_sessions,
        fixture_measurement=args.fixture_measurement,
        base_branch=args.base_branch,
        allow_gh=allow_gh,
    )


if __name__ == "__main__":
    raise SystemExit(main())
