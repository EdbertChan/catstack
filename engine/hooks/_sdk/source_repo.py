"""Where an installed catstack hook came from.

install.sh copies engine/hooks into a snapshot directory and writes
`.catstack-source` at its root: line 1 the checkout, line 2 the commit,
line 3 the branch. A hook file reached from that snapshot must read the
checkout from the record; walking up from its own path lands in the home
directory instead.
"""
from __future__ import annotations

import os

SOURCE_MARKER = ".catstack-source"
UNKNOWN_SHA = "unknown"


def read_marker(snapshot_root: str) -> tuple[str | None, str | None, str | None]:
    """(repo, sha, branch) recorded at snapshot_root; None for each value not recorded."""
    try:
        with open(os.path.join(snapshot_root, SOURCE_MARKER), encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return None, None, None

    def line(index: int) -> str | None:
        value = lines[index].strip() if len(lines) > index else ""
        return value or None

    sha = line(1)
    if sha == UNKNOWN_SHA:
        sha = None
    return line(0), sha, line(2)


def is_checkout(path: str) -> bool:
    return os.path.exists(os.path.join(path, ".git"))


def source_repo(hook_file: str) -> str | None:
    """The catstack checkout hook_file was installed from, or None when it cannot be told."""
    hook_dir = os.path.dirname(os.path.realpath(hook_file))
    hooks_root = os.path.dirname(hook_dir)
    repo, _sha, _branch = read_marker(hooks_root)
    if repo and is_checkout(repo):
        return repo
    checkout = os.path.dirname(os.path.dirname(hooks_root))
    if is_checkout(checkout):
        return checkout
    return None
