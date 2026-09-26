#!/usr/bin/env python3
"""Codex UserPromptSubmit entrypoint for offscope-session.

Same single call as the other two entrypoints: `detect.detect` reports the
previous prompt's verdict first, then asks about this one.
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
        "codex",
        detect,
        "UserPromptSubmit",
        legacy_fail_open_context="codex_prompt_submit fail-open during off-scope detection",
    )


if __name__ == "__main__":
    main()
