#!/usr/bin/env python3
"""Tell a line that only follows a moved file from a line that says something new.

Moving a file rewrites every line that names it. The pull request checks read
diffs, and without this they read those lines as newly written: a rule
sentence for the skill coverage check, a comment for the comment check.
`follows_moved_file` pairs a removed line with its added twin and passes the
pair only when every changed word is a path that keeps its file name and whose
new path exists. Any other change is left for the check to judge.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Iterator

PATH_TOKEN_RE = re.compile(r"([\w.-]+(?:/[\w.-]+)*\.[A-Za-z0-9]+)")
HEADER_PREFIXES = ("--- a/", "--- /dev/null", "+++ b/", "+++ /dev/null")


def follows_moved_file(removed: str, added: str, exists: Callable[[str], bool]) -> bool:
    old_parts = PATH_TOKEN_RE.split(removed)
    new_parts = PATH_TOKEN_RE.split(added)
    if len(old_parts) != len(new_parts) or old_parts == new_parts:
        return False
    for index, (old, new) in enumerate(zip(old_parts, new_parts)):
        if old == new:
            continue
        if index % 2 == 0 or Path(old).name != Path(new).name or not exists(new):
            return False
    return True


def diff_hunks(diff_text: str) -> Iterator[tuple[str | None, list[str], list[str]]]:
    """Yield (b-side path, removed lines, added lines) for each hunk of a unified diff."""
    path: str | None = None
    removed: list[str] = []
    added: list[str] = []
    for raw in diff_text.splitlines():
        if raw.startswith(HEADER_PREFIXES) or raw.startswith("@@") or raw.startswith("diff --git "):
            if removed or added:
                yield path, removed, added
            removed, added = [], []
            if raw.startswith("+++ b/"):
                path = raw[6:]
            elif raw.startswith(("+++ /dev/null", "diff --git ")):
                path = None
            continue
        if raw.startswith("-"):
            removed.append(raw[1:])
        elif raw.startswith("+"):
            added.append(raw[1:])
    if removed or added:
        yield path, removed, added


def new_lines(removed: list[str], added: list[str], exists: Callable[[str], bool]) -> list[str]:
    """The added lines of one hunk that are not a moved-file twin of the removed line at the same position."""
    if len(removed) != len(added):
        return list(added)
    return [line for old, line in zip(removed, added) if not follows_moved_file(old, line, exists)]
