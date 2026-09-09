#!/usr/bin/env python3
"""Create throwaway git repositories for tests with background maintenance off.

Since git 2.55, `git commit` starts `git maintenance run --auto --detach`: a
setsid'd process that keeps writing into `.git/objects` -- repack temp
indexes, `objects/info/packs`, `objects/maintenance.lock` -- after the
foreground command has already exited. A `tempfile.TemporaryDirectory`
cleanup landing in that window fails with `OSError: [Errno 39] Directory not
empty: 'objects'`. Setting `gc.auto` and `maintenance.auto` stops git from
spawning that process at all, on both the old and the new invocation.

The settings are written into the new repository's own config rather than
the environment, so they survive tests that hand their git subprocesses a
replacement `env` mapping.
"""
from __future__ import annotations

import subprocess

MAINTENANCE_OFF = (("gc.auto", "0"), ("maintenance.auto", "false"))


def disable_background_maintenance(root, env=None) -> None:
    """Turn off auto gc and auto maintenance in an already-created repo."""
    for key, value in MAINTENANCE_OFF:
        subprocess.run(
            ["git", "-C", str(root), "config", key, value],
            check=True,
            capture_output=True,
            env=env,
        )


def init_repo(root, *init_args: str, env=None) -> str:
    """`git init` a repo at ``root`` that will not spawn background git."""
    subprocess.run(
        ["git", "init", "-q", *init_args, str(root)],
        check=True,
        capture_output=True,
        env=env,
    )
    disable_background_maintenance(root, env=env)
    return str(root)
