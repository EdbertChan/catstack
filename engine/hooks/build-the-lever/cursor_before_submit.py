#!/usr/bin/env python3
"""Cursor beforeSubmitPrompt entrypoint for build-the-lever."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

from detect import detect  # noqa: E402
from runtime import run_hook  # noqa: E402


def main() -> None:
    run_hook("build-the-lever", "cursor", detect, "beforeSubmitPrompt")


if __name__ == "__main__":
    main()
