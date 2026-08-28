#!/usr/bin/env python3
"""Reject local-only artifacts that have been added to the Git index."""
from __future__ import annotations

import subprocess
from collections.abc import Iterable
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def forbidden_tracked_paths(paths: Iterable[str]) -> list[str]:
    """Return tracked paths covered by the local-artifact policy."""
    forbidden: list[str] = []
    for path in paths:
        segments = path.split("/")
        if (
            path.startswith(".worktrees/")
            or "__pycache__" in segments
            or path.endswith(".pyc")
        ):
            forbidden.append(path)
    return forbidden


def main() -> int:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or "git ls-files failed"
        print(f"check_no_tracked_local_artifacts: ERROR: {detail}")
        return 2

    forbidden = forbidden_tracked_paths(result.stdout.splitlines())
    if forbidden:
        print("check_no_tracked_local_artifacts: FAIL")
        for path in forbidden:
            print(f"  - {path}")
        print("Remove the listed paths from the Git index and rerun this check.")
        return 1

    print("check_no_tracked_local_artifacts: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
