#!/usr/bin/env python3
"""Portable stand-in for Apple's plutil, limited to `-lint`.

scripts/install ships launchd plists whose proof commands run
`plutil -lint <path>`. Only macOS ships plutil, so on every other host that
proof dies with "plutil: command not found" instead of checking the plist.
scripts/test/ensure_plutil_toolchain.sh installs this file as `plutil` on
those hosts. It prints "<path>: OK" and exits 0 when plistlib parses the file,
prints the parse error and exits 1 when it does not, and exits 2 on any other
plutil flag so a file this shim cannot check never reads as a clean one.
"""
from __future__ import annotations

import plistlib
import sys

USAGE = "plutil shim: only `-lint FILE...` is supported"


def lint(path: str) -> str:
    """Return an empty string when path parses as a plist, else the reason."""
    try:
        with open(path, "rb") as handle:
            plistlib.load(handle)
    except FileNotFoundError:
        return "file does not exist"
    except OSError as error:
        return f"cannot read: {error}"
    except Exception as error:
        return f"{type(error).__name__}: {error}"
    return ""


def main(argv: list[str]) -> int:
    """Run the plutil subset this shim supports: `-lint FILE...`."""
    if not argv or argv[0] != "-lint":
        given = " ".join(argv) if argv else "(no arguments)"
        sys.stderr.write(f"{USAGE}; refusing to report a pass for: {given}\n")
        return 2
    paths = argv[1:]
    if not paths:
        sys.stderr.write(f"{USAGE}; no file was given to lint\n")
        return 2
    status = 0
    for path in paths:
        reason = lint(path)
        if reason:
            sys.stderr.write(f"{path}: {reason}\n")
            status = 1
        else:
            print(f"{path}: OK")
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
