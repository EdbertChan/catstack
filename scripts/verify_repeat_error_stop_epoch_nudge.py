#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMMANDS = (
    ("python3", "-m", "unittest", "discover", "-s", "engine/hooks/repeat-error-stop/tests", "-v"),
    ("python3", "scripts/check_hook_test_coverage.py", "engine/hooks/repeat-error-stop"),
    ("python3", "scripts/check_no_new_comments.py", "--base", "origin/main"),
    ("python3", "engine/hooks/repeat-error-stop/backtest.py", "--help"),
)


def main() -> int:
    for command in COMMANDS:
        print("$ " + " ".join(command), flush=True)
        result = subprocess.run(command, cwd=ROOT)
        if result.returncode != 0:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
