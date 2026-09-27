#!/usr/bin/env python3
"""Check or write explicit SubagentStop dispatcher opt-ins on Stop manifests."""
from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path
import sys


REPO_DIR = Path(__file__).resolve().parents[2]
HOOKS_DIR = REPO_DIR / "engine" / "hooks"


def stop_manifests(hooks_dir: Path) -> list[tuple[Path, dict]]:
    found = []
    for raw_path in sorted(glob.glob(str(hooks_dir / "*" / "claude*.hook.json"))):
        path = Path(raw_path)
        with path.open(encoding="utf-8") as handle:
            manifest = json.load(handle)
        if isinstance(manifest, dict) and manifest.get("hooks", {}).get("Stop"):
            found.append((path, manifest))
    return found


def expected(path: Path, manifest: dict) -> bool | str:
    opt_out = manifest.get("subagent_stop")
    if isinstance(opt_out, dict) and opt_out.get("inherit") is False:
        return False
    if path.parent.name == "diu-stop":
        return "claude_stop_check.py:detect"
    return True


def update(path: Path, manifest: dict, write: bool) -> bool:
    wanted = expected(path, manifest)
    dispatch = manifest.get("dispatch")
    actual = dispatch.get("SubagentStop") if isinstance(dispatch, dict) else None
    if actual == wanted or wanted is False and actual in (None, False):
        return False
    if not write:
        return True
    if wanted:
        manifest["dispatch"] = {**(dispatch if isinstance(dispatch, dict) else {}), "SubagentStop": wanted}
    elif isinstance(dispatch, dict):
        dispatch.pop("SubagentStop", None)
        if not dispatch:
            manifest.pop("dispatch", None)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--hooks-dir", default=str(HOOKS_DIR))
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    changed = []
    try:
        for path, manifest in stop_manifests(Path(args.hooks_dir)):
            if update(path, manifest, args.write):
                changed.append(os.path.relpath(path, REPO_DIR))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as exc:
        print(f"subagent-stop-dispatch-opt-in: could not check manifests: {exc}", file=sys.stderr)
        return 2
    if changed:
        action = "updated" if args.write else "missing explicit opt-in"
        for path in changed:
            print(f"{action}: {path}")
        return 0 if args.write else 1
    print("subagent-stop-dispatch-opt-in: all Stop manifests are explicit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
