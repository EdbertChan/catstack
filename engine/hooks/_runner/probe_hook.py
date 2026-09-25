#!/usr/bin/env python3
"""A hook that exists only to be run by the doctor.

The doctor's last question is whether the runner can actually reach a hook and
hand back what it printed. Asking that of a real hook would write that hook's
state and its findings into the user's own session, so the question gets its
own subject instead: this file reads its stdin, prints one marker, and exits 0.

It lives under `_runner/` because the installed-hook sweep skips directories
whose name starts with an underscore, so the probe is never mistaken for a
hook that ships behaviour.
"""
from __future__ import annotations

import sys

MARKER = "catstack-hook-doctor: probe reached"


def main() -> int:
    sys.stdin.buffer.read()
    sys.stdout.write(MARKER + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
