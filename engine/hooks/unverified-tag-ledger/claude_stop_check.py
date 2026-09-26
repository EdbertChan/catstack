#!/usr/bin/env python3
"""Claude Code Stop hook: record well-formed CAT-UNVERIFIED tags against the
session, and refuse a turn that tags a claim without having run any
verification tool (cat-mode/SKILL.md:269 -- a hedge is a trigger to verify).
`stop_hook_active` releases that refusal so the rewrite turn can finish. With
CATSTACK_UNVERIFIED_TAG_BEHAVIOR=do_not_emit it also refuses any reply that
carries a tag. Fails open on read or parse errors.
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
        "Stop",
        legacy_fail_open_context="detector error, allowing this reply",
    )


if __name__ == "__main__":
    main()
