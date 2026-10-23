#!/usr/bin/env python3
"""Plan the reflect apply worktrees from the Accepted items' target paths.

Step 5 of reflect spawns one apply agent per worktree. make-pr opens one PR
per review unit, and its preflight splits a slice that mixes units. Grouping
worktrees by owning repo alone therefore hands one agent a slice that
preflight later splits in two. This script reads the same unit rules that
preflight reads (drafter.config.json) and prints one row per
(owning repo, review unit) before anything is spawned: worktree directory,
branch name, and the paths that row owns.

    python3 apply_plan.py --topic unchecked-hooks engine/hooks/_sdk/runtime.py corpus/CLAUDE.learned.md
    python3 apply_plan.py --item A1=engine/skills/reflect/SKILL.md --item A2=engine/hooks/x/detect.py
    python3 apply_plan.py --json PATH...

A relative path belongs to the catstack checkout that holds this script. An
absolute path belongs to the git checkout that contains it; an external
checkout with no drafter.config.json gets one row named `repo`.

Exit 0 when every item has at least one path and the plan printed. Exit 1
for an Accepted item with no target path, or no paths at all. Exit 3 when
the unit rules could not be read (unchecked, not clean).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPTS_DIR, "..", "..", "..", ".."))
MAKE_PR_SCRIPTS = os.path.join(REPO_ROOT, "engine", "skills", "make-pr", "scripts")
if MAKE_PR_SCRIPTS not in sys.path:
    sys.path.insert(0, MAKE_PR_SCRIPTS)

import preflight  # noqa: E402

EXTERNAL_UNIT = "repo"
UNCHECKED_EXIT = preflight.UNCHECKED_EXIT
WORKTREES_DIR = ".worktrees"


def _git_toplevel(path: str) -> str | None:
    probe = path if os.path.isdir(path) else os.path.dirname(path)
    result = subprocess.run(
        ["git", "-C", probe, "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        return None
    return os.path.realpath(result.stdout.strip())


def owning_repo(path: str, repo_root: str) -> tuple[str, str]:
    """(repo root, path relative to it) for one target path."""
    root = os.path.realpath(repo_root)
    if not os.path.isabs(path):
        return root, path.replace("\\", "/")
    real = os.path.realpath(path)
    if real == root or real.startswith(root + os.sep):
        return root, os.path.relpath(real, root).replace("\\", "/")
    toplevel = _git_toplevel(real)
    if toplevel is None:
        raise ValueError(f"{path}: not inside a git checkout; cannot name its owning repo")
    return toplevel, os.path.relpath(real, toplevel).replace("\\", "/")


def units_for_repo(repo_root: str, rel_paths: list[str], catstack_root: str) -> dict:
    config = os.path.join(repo_root, "drafter.config.json")
    if os.path.realpath(repo_root) != os.path.realpath(catstack_root) and not os.path.isfile(config):
        return {"units": {EXTERNAL_UNIT: list(rel_paths)}, "neutral": []}
    return preflight.classify(rel_paths, config if os.path.isfile(config) else None)


def plan(
    paths: list[str],
    *,
    topic: str,
    stamp: str,
    repo_root: str = REPO_ROOT,
    worktrees_dir: str = WORKTREES_DIR,
) -> list[dict]:
    by_repo: dict[str, list[str]] = {}
    for path in paths:
        root, rel = owning_repo(path, repo_root)
        by_repo.setdefault(root, []).append(rel)
    rows: list[dict] = []
    for root in sorted(by_repo):
        classified = units_for_repo(root, by_repo[root], repo_root)
        units = classified["units"]
        neutral = list(classified["neutral"])
        if not units and neutral:
            units = {EXTERNAL_UNIT: []}
        for index, unit in enumerate(sorted(units)):
            owned = list(units[unit]) + (neutral if index == 0 else [])
            rows.append({
                "repo": root,
                "unit": unit,
                "worktree": os.path.join(root, worktrees_dir, f"reflect-{topic}-{unit}"),
                "branch": f"reflect/{topic}-{unit}-{stamp}",
                "paths": owned,
            })
    return rows


def parse_items(items: list[str]) -> tuple[list[str], list[str]]:
    """(paths, empty item labels) from LABEL=path[,path] arguments."""
    paths: list[str] = []
    empty: list[str] = []
    for item in items:
        label, _sep, raw = item.partition("=")
        found = [p for p in raw.split(",") if p.strip()]
        if not found:
            empty.append(label or item)
        paths.extend(found)
    return paths, empty


def render(rows: list[dict]) -> str:
    lines = [f"plan\t{len(rows)} worktree(s)"]
    for row in rows:
        lines.append(
            f"row\t{row['repo']}\t{row['unit']}\t{row['worktree']}\t{row['branch']}\t"
            + ",".join(row["paths"])
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", help="Accepted items' target paths")
    ap.add_argument("--item", action="append", default=[], help="LABEL=path[,path]; an item with no path fails")
    ap.add_argument("--topic", default="apply", help="short topic for the worktree and branch names")
    ap.add_argument("--date", default=date.today().strftime("%Y%m%d"), help="yyyymmdd suffix for the branch")
    ap.add_argument("--repo-root", default=REPO_ROOT, help="the catstack checkout relative paths belong to")
    ap.add_argument("--json", action="store_true", help="machine-readable rows")
    args = ap.parse_args(argv)

    item_paths, empty = parse_items(args.item)
    paths = list(args.paths) + item_paths
    if empty:
        for label in empty:
            print(f"fail\tAccepted item {label} names no target path", file=sys.stderr)
        return 1
    if not paths:
        print("fail\tno target paths given", file=sys.stderr)
        return 1
    try:
        rows = plan(paths, topic=args.topic, stamp=args.date, repo_root=args.repo_root)
    except preflight.UnitRulesUnreadable as exc:
        print(f"unchecked\treview-unit rules could not be read: {exc}", file=sys.stderr)
        return UNCHECKED_EXIT
    except ValueError as exc:
        print(f"fail\t{exc}", file=sys.stderr)
        return 1
    print(json.dumps(rows, indent=2) if args.json else render(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
