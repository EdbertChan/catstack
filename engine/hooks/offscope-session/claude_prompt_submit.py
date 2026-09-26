#!/usr/bin/env python3
"""Claude Code UserPromptSubmit entrypoint for offscope-session.

One event does both halves of the hook, in this order: report the verdict the
judge left for the previous prompt, then enqueue the question about this one.
`detect.detect` is what enforces the order, and all three harness entrypoints
call that same function, so none of them can drift into its own detection.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

from detect import detect  # noqa: E402
from runtime import run_hook  # noqa: E402


def main() -> None:
    run_hook(
        "offscope-session",
        "claude",
        detect,
        "UserPromptSubmit",
        legacy_fail_open_context="claude_prompt_submit fail-open during off-scope detection",
    )


if __name__ == "__main__":
    main()
