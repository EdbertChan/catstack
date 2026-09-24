#!/usr/bin/env python3
"""Claude Code UserPromptSubmit entrypoint for restated-constraint."""
from __future__ import annotations

import sys
from pathlib import Path

SDK_DIR = Path(__file__).resolve().parents[1] / "_sdk"
sys.path.insert(0, str(SDK_DIR))

from detect import detect
from runtime import run_hook


def main() -> None:
    run_hook("restated-constraint", "claude", detect, "UserPromptSubmit", json_error_stderr=False)


if __name__ == "__main__":
    main()
