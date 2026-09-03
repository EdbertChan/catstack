#!/usr/bin/env python3
"""Fail when a diff against the base adds comment lines to code files.

CI twin of engine/hooks/no-comments. Same detector, same allowed directives.

    python3 scripts/check_no_new_comments.py            # diff vs origin/main
    python3 scripts/check_no_new_comments.py --base main
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "engine", "hooks", "no-comments"))

from detect import comment_lines, is_code_file  # noqa: E402


def added_lines_by_file(diff_text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    current: str | None = None
    for raw in diff_text.splitlines():
        if raw.startswith("+++ b/"):
            current = raw[6:]
            continue
        if raw.startswith(("+++ ", "--- ", "@@")):
            if raw.startswith("+++ "):
                current = None
            continue
        if current and raw.startswith("+") and not raw.startswith("+++"):
            out.setdefault(current, []).append(raw[1:])
    return out


def check(diff_text: str) -> list[str]:
    problems: list[str] = []
    for path, lines in added_lines_by_file(diff_text).items():
        if not is_code_file(path):
            continue
        for hit in comment_lines(path, "\n".join(lines)):
            problems.append(f"{path}: + {hit[:100]}")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="origin/main")
    args = ap.parse_args(argv)
    mb = subprocess.run(["git", "-C", REPO_ROOT, "merge-base", args.base, "HEAD"], capture_output=True, text=True)
    if mb.returncode != 0:
        print(f"fail  cannot resolve merge-base with {args.base}: {mb.stderr.strip()}", file=sys.stderr)
        return 2
    diff = subprocess.run(["git", "-C", REPO_ROOT, "diff", mb.stdout.strip()], capture_output=True, text=True, check=True).stdout
    problems = check(diff)
    for p in problems:
        print("fail  " + p, file=sys.stderr)
    if problems:
        print(f"fail  {len(problems)} new comment line(s); comments are banned in code (see engine/hooks/no-comments)", file=sys.stderr)
        return 1
    print("ok      no new comments")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
