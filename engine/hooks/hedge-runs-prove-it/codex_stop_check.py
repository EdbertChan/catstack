#!/usr/bin/env python3
"""Codex Stop hook entrypoint for hedge-runs-prove-it."""
from __future__ import annotations

import sys
from pathlib import Path

HOOK_DIR = Path(__file__).resolve().parent
SDK_DIR = HOOK_DIR.parent / "_sdk"
sys.path.insert(0, str(SDK_DIR))
sys.path.insert(0, str(HOOK_DIR))

from detect import detect  # noqa: E402
from runtime import run_hook  # noqa: E402


def main() -> None:
    run_hook("hedge-runs-prove-it", "codex", detect)


if __name__ == "__main__":
    main()
