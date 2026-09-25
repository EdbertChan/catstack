#!/usr/bin/env python3
"""Claude UserPromptSubmit entrypoint for hook-freshness."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

from detect import detect, maybe_reinstall  # noqa: E402
from runtime import run_hook  # noqa: E402


def _detect(event):
    """Auto-reinstall when the pinned checkout moved past a hook or skill
    change, then return the freshness findings. run_hook only calls this after
    the payload parsed, so a garbage prompt never triggers a reinstall, and the
    trigger stays on the Claude entrypoint only."""
    try:
        maybe_reinstall(event)
    except Exception as exc:
        print(f"catstack-hook-error hook-freshness: {type(exc).__name__}: {exc}", file=sys.stderr)
    return detect(event)


def main() -> None:
    try:
        run_hook("hook-freshness", "claude", _detect, "UserPromptSubmit", json_error_stderr=False)
    except SystemExit as exc:
        if exc.code not in (0, None):
            raise


if __name__ == "__main__":
    main()
