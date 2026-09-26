#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook: surface CAT-UNVERIFIED claims that
earlier turns deferred and never settled. This is where cat-mode/SKILL.md:269
gets teeth -- the Stop hook cannot block the turn that emits a tag without
deadlocking, so the reminder lands on the next prompt instead.

How much it says is CATSTACK_UNVERIFIED_TAG_BEHAVIOR: off, stale (default),
all, or do_not_emit. Rows keep being recorded on every setting. do_not_emit
replaces the list with a standing instruction to leave unchecked claims out;
the Stop hook enforces it.
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
        "unverified-tag-ledger",
        "claude",
        detect,
        "UserPromptSubmit",
        legacy_fail_open_context="reminder error, continuing",
    )


if __name__ == "__main__":
    main()
