"""Identity of the Invoker install that is on PATH.

A packaged install only has a binary version. A source checkout also has a
git commit. Both are cached for the process so a hook fire does not start
a new process for every row.
"""
from __future__ import annotations

import os
import shutil
import subprocess

_INVOKER_VERSION: str | None = None
_INVOKER_SHA: str | None = None


def invoker_version() -> str:
    global _INVOKER_VERSION
    if _INVOKER_VERSION is None:
        _INVOKER_VERSION = _read_version()
    return _INVOKER_VERSION


def invoker_sha() -> str:
    global _INVOKER_SHA
    if _INVOKER_SHA is None:
        _INVOKER_SHA = _read_sha()
    return _INVOKER_SHA


def _read_version() -> str:
    path = shutil.which("invoker-cli")
    if not path:
        return ""
    try:
        out = subprocess.check_output(
            [path, "--version"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.strip().splitlines()[0].strip() if out.strip() else ""


def _read_sha() -> str:
    path = shutil.which("invoker-cli")
    if not path:
        return ""
    root = _source_root(os.path.realpath(path))
    if not root:
        return ""
    try:
        out = subprocess.check_output(
            ["git", "-C", root, "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.strip()


def _source_root(start: str) -> str:
    """Repo root above a developer checkout. Empty for a packaged binary."""
    current = os.path.dirname(start)
    while True:
        if os.path.isfile(os.path.join(current, "pnpm-workspace.yaml")) and os.path.isdir(
            os.path.join(current, ".git")
        ):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return ""
        current = parent
