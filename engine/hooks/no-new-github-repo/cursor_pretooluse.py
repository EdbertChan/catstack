#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SDK_DIR = os.path.join(os.path.dirname(HERE), "_sdk")
for path in (HERE, SDK_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from detect import run  # noqa: E402

if __name__ == "__main__":
    run("cursor", "preToolUse")
