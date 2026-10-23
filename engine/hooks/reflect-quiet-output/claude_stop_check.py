#!/usr/bin/env python3
"""Claude Code Stop hook: after a reflect invocation this turn, the reply is
one sentence with the PR link; the findings live in the PR body. Blocks with
exit 2; an unreadable transcript is unchecked and fails open;
`stop_hook_active` skips so the rewrite turn can finish.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

from detect import detect  # noqa: E402
from runtime import run_hook  # noqa: E402


def main() -> None:
    try:
        run_hook(
            "reflect-quiet-output",
            "claude",
            detect,
            "Stop",
            json_error_stderr=False,
        )
    except SystemExit as exc:
        if exc.code in (0, None):
            return
        raise


if __name__ == "__main__":
    main()
