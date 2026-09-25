#!/usr/bin/env python3
from __future__ import annotations

from install_common import install

if __name__ == "__main__":
    install("cursor", "~/.cursor/hooks.json", {"version": 1, "hooks": {}})
