#!/usr/bin/env python3
"""Claude Code PreToolUse entrypoint: diu's cap on a reply to a comment on a document."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

from comment_reply import detect  # noqa: E402
from runtime import run_hook  # noqa: E402


def main() -> None:
    run_hook("diu-stop", "claude", detect, "PreToolUse", inspect_raw_payload=True)


if __name__ == "__main__":
    main()
