#!/usr/bin/env python3
"""Fail when a diff against the base adds comment lines to code files.

CI twin of engine/hooks/no-comments. Same detector, same allowed directives.
The diff uses copy detection, and a line whose only change is a moved file's
path is not read as new (scripts/ci/moved_paths.py), so moving a script does not
turn its existing comments into added ones.

    python3 scripts/ci/check_no_new_comments.py            # diff vs origin/main
    python3 scripts/ci/check_no_new_comments.py --base main
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

SCRIPTS_DIR = os.path.dirname(os.path.realpath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(SCRIPTS_DIR))
sys.path.insert(0, os.path.join(REPO_ROOT, "engine", "hooks", "no-comments"))
sys.path.insert(0, SCRIPTS_DIR)

from detect import comment_lines, is_code_file  # noqa: E402
from moved_paths import diff_hunks, new_lines  # noqa: E402

PROMISED_CATCH = (
    "scripts/demo.py: # explain the loop",
    "scripts/demo.py: total = 0  # explain the loop",
    "scripts/demo.sh: # explain the loop",
    "src/app.ts: // explain the loop",
    "src/app.ts: /* explain the loop */",
)
PROMISED_ALLOW = (
    "scripts/demo.py: #!/usr/bin/env python3",
    "scripts/demo.py: import os  # noqa: F401",
    "scripts/demo.py: # SPDX-License-Identifier: MIT",
    "src/app.ts: // eslint-disable-next-line no-console",
    "scripts/demo.py: url = 'https://example.com/#anchor'",
    "docs/demo.md: # Heading",
    "config/app.yaml: # a yaml comment",
)


def flags_exemplar(exemplar: str) -> bool:
    path, line = exemplar.split(": ", 1)
    return bool(check(f"+++ b/{path}\n+{line}\n"))


def _exists_in_checkout(path: str) -> bool:
    return os.path.exists(os.path.join(REPO_ROOT, path))


def added_lines_by_file(diff_text: str, exists=_exists_in_checkout) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for path, removed, added in diff_hunks(diff_text):
        if path is None:
            continue
        lines = new_lines(removed, added, exists)
        if lines:
            out.setdefault(path, []).extend(lines)
    return out


def diff_since(base_commit: str, cwd: str = REPO_ROOT) -> str:
    return subprocess.run(["git", "-C", cwd, "diff", "-C", base_commit], capture_output=True, text=True, check=True).stdout


def check(diff_text: str, exists=_exists_in_checkout) -> list[str]:
    problems: list[str] = []
    for path, lines in added_lines_by_file(diff_text, exists).items():
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
    diff = diff_since(mb.stdout.strip())
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
