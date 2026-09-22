#!/usr/bin/env python3
"""Load every installed hook script and report the ones whose imports fail.

install.sh links hook directories into $HOME/.claude|.cursor|.codex/hooks and
exits 0 when every link is in place. A link is not a working hook: an entry
script resolves its shared modules (`_sdk`, `_markers`, `_flags`) through the
installed hooks directory, so a helper directory the installer never linked
leaves the hook raising ModuleNotFoundError on its first real event, with no
failure anywhere in the install output. That is the gap this closes -- the
deployed artifact gets smoke-tested, not just the build (Humble & Farley,
*Continuous Delivery*, 2010, https://continuousdelivery.com/).

Each script is imported under its own module name, never run as `__main__`, so
a `if __name__ == "__main__":` entry point does not execute and no hook does
real work here. The loader first puts the script's own resolved directory on
`sys.path`, which is what the interpreter does for a script it runs: a hook
imports its siblings (`detect`, `state`) that way, and a sweep without it would
report every hook as broken. Resolved, not merely absolute, for the same reason
-- a hook directory under `$HOME/.claude/hooks` is a symlink into the checkout,
and the interpreter hands a real run the resolved path. The outcome comes from
the child's exit code, a typed signal, not from matching words in its stderr:

  * `IMPORT_FAIL_EXIT` -- the child caught ImportError (ModuleNotFoundError is
    a subclass) while loading the module. This is the failure this checks for.
  * `0` -- the module loaded, or raised something else at import time, which is
    the module's own business and not an install defect.
  * timeout -- the module was still doing work at import time. Reported as
    `slow`; imports resolve before that point, so it is not a failure.

A sweep that finds no scripts exits 2 (`unchecked`): an empty sweep means the
hooks directories are missing or unreadable, which is not a clean pass.
"""
from __future__ import annotations

import argparse
import glob
import os
import subprocess
import sys

HARNESS_DIRS = (".claude", ".cursor", ".codex")
SKIP_PREFIXES = ("install_", "test_")
SKIP_NAMES = ("detect.py", "state.py")
DEFAULT_TIMEOUT = 5.0
IMPORT_FAIL_EXIT = 97

LOADER = """
import importlib.util, os, sys
path = sys.argv[1]
sys.path.insert(0, os.path.realpath(os.path.dirname(path)))
spec = importlib.util.spec_from_file_location("catstack_hook_under_smoke", path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
try:
    spec.loader.exec_module(module)
except ImportError as exc:
    sys.stderr.write(f"{type(exc).__name__}: {exc}\\n")
    sys.exit(%d)
except BaseException:
    sys.exit(0)
""" % IMPORT_FAIL_EXIT


def entry_scripts(home: str) -> list[str]:
    """Every installed hook entry script, in a stable order.

    Shared-module directories (`_sdk`, `_flags`, ...) are libraries, and
    `install_*.py` / `test_*.py` / `detect.py` / `state.py` are not entry
    points, so none of them are loaded here.
    """
    found: list[str] = []
    for harness in HARNESS_DIRS:
        pattern = os.path.join(home, harness, "hooks", "*", "*.py")
        for path in sorted(glob.glob(pattern)):
            hook = os.path.basename(os.path.dirname(path))
            name = os.path.basename(path)
            if hook.startswith("_") or name.startswith(SKIP_PREFIXES) or name in SKIP_NAMES:
                continue
            found.append(path)
    return found


def classify(path: str, timeout: float, run=subprocess.run) -> tuple[str, str]:
    """(outcome, detail) for one script: ok, import-fail, or slow."""
    try:
        result = run(
            [sys.executable, "-c", LOADER, path],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "slow", f"still loading after {timeout:g}s"
    if result.returncode == IMPORT_FAIL_EXIT:
        return "import-fail", (result.stderr or "").strip().splitlines()[-1]
    return "ok", f"exit={result.returncode}"


def sweep(home: str, timeout: float = DEFAULT_TIMEOUT, run=subprocess.run) -> tuple[list[str], list[str], int]:
    """(import failures, slow scripts, number checked)."""
    failures: list[str] = []
    slow: list[str] = []
    scripts = entry_scripts(home)
    for path in scripts:
        outcome, detail = classify(path, timeout, run=run)
        shown = os.path.relpath(path, home)
        if outcome == "import-fail":
            failures.append(f"{shown}: {detail}")
        elif outcome == "slow":
            slow.append(f"{shown}: {detail}")
    return failures, slow, len(scripts)


def main(argv: list[str] | None = None, stdout=None, run=subprocess.run) -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the installed hook scripts.")
    parser.add_argument("--home", default=os.path.expanduser("~"))
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    args = parser.parse_args(argv)
    out = stdout or sys.stdout

    failures, slow, checked = sweep(args.home, timeout=args.timeout, run=run)
    for line in failures:
        out.write(f"FAIL    {line}\n")
    for line in slow:
        out.write(f"slow    {line} (imports resolved; still working)\n")
    out.write(f"hook import smoke: checked={checked} import-fail={len(failures)} slow={len(slow)}\n")
    if not checked:
        out.write(
            f"hook import smoke: UNCHECKED -- no hook scripts found under {args.home}; "
            "the hooks directories are missing or unreadable, so nothing was verified.\n"
        )
        return 2
    if failures:
        out.write(
            "hook import smoke: those scripts cannot load their shared modules, so the hooks "
            "they back never run. Check that install.sh links every shared directory they import.\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
