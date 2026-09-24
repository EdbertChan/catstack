#!/usr/bin/env python3
"""Open and load every installed hook script; report the ones a real run cannot.

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

  * `UNREADABLE_EXIT` -- the child could not `open()` the script at all. A link
    can resolve, `stat()` can succeed, and `open()` can still fail: a dangling
    symlink target, a mode the running user cannot read, or -- on macOS -- a
    TCC/Full Disk Access denial on a checkout under `~/Documents`, which is
    where this repo lives. Existence tests (`test -f`) and `glob` both go
    through `stat()`, so they pass throughout that failure while every real
    hook run dies. The child opens the file before importing anything, so the
    probe is the same syscall, in the same interpreter, a real run makes.
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
UNREADABLE_EXIT = 96
DOCUMENTS = "~/Documents"

LOADER = """
import importlib.util, os, sys
path = sys.argv[1]
try:
    with open(path, "rb") as handle:
        handle.read(1)
except OSError as exc:
    sys.stderr.write(f"{type(exc).__name__}: {exc}\\n")
    sys.exit(96)
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


def documents_root() -> str:
    """The resolved `~/Documents`, which is the only form a target can match.

    A reported target is `os.path.realpath`'d, so the prefix it is tested
    against has to be resolved too. Documents is itself a symlink on every Mac
    that keeps it on iCloud Drive or an external volume: there the resolved
    target starts with the volume, never with `~/Documents`, so an unresolved
    prefix matches nothing and the Full Disk Access hint goes missing on
    exactly the setups that need it.
    """
    return os.path.realpath(os.path.expanduser(DOCUMENTS))


def under_documents(target: str) -> bool:
    """Is this resolved path inside the resolved `~/Documents`?"""
    root = documents_root()
    return target == root or target.startswith(root + os.sep)


def _last_stderr_line(result) -> str:
    lines = (result.stderr or "").strip().splitlines()
    return lines[-1] if lines else f"exit={result.returncode}, no stderr"


def classify(path: str, timeout: float, run=subprocess.run) -> tuple[str, str]:
    """(outcome, detail) for one script: ok, unreadable, import-fail, or slow."""
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
    if result.returncode == UNREADABLE_EXIT:
        return "unreadable", _last_stderr_line(result)
    if result.returncode == IMPORT_FAIL_EXIT:
        return "import-fail", _last_stderr_line(result)
    return "ok", f"exit={result.returncode}"


def sweep(
    home: str, timeout: float = DEFAULT_TIMEOUT, run=subprocess.run
) -> tuple[list[tuple[str, str, str]], list[str], list[str], int]:
    """(unreadable scripts, import failures, slow scripts, number checked).

    An unreadable script is kept as `(installed path, resolved target, detail)`
    rather than one formatted line: the link is what the installer wrote, the
    target is what the denial is actually about, and the caller decides which
    cause to name from the target itself instead of searching printed text.
    """
    unreadable: list[tuple[str, str, str]] = []
    failures: list[str] = []
    slow: list[str] = []
    scripts = entry_scripts(home)
    for path in scripts:
        outcome, detail = classify(path, timeout, run=run)
        shown = os.path.relpath(path, home)
        if outcome == "unreadable":
            unreadable.append((shown, os.path.realpath(path), detail))
        elif outcome == "import-fail":
            failures.append(f"{shown}: {detail}")
        elif outcome == "slow":
            slow.append(f"{shown}: {detail}")
    return unreadable, failures, slow, len(scripts)


def main(argv: list[str] | None = None, stdout=None, run=subprocess.run) -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the installed hook scripts.")
    parser.add_argument("--home", default=os.path.expanduser("~"))
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    args = parser.parse_args(argv)
    out = stdout or sys.stdout

    unreadable, failures, slow, checked = sweep(args.home, timeout=args.timeout, run=run)
    for shown, target, detail in unreadable:
        out.write(f"FAIL    {shown} -> {target}: {detail}\n")
    for line in failures:
        out.write(f"FAIL    {line}\n")
    for line in slow:
        out.write(f"slow    {line} (imports resolved; still working)\n")
    out.write(
        f"hook import smoke: checked={checked} unreadable={len(unreadable)} "
        f"import-fail={len(failures)} slow={len(slow)}\n"
    )
    if not checked:
        out.write(
            f"hook import smoke: UNCHECKED -- no hook scripts found under {args.home}; "
            "the hooks directories are missing or unreadable, so nothing was verified.\n"
        )
        return 2
    if unreadable:
        out.write(
            "hook import smoke: those scripts exist but cannot be opened by the interpreter that "
            "runs them, so every hook they back dies on its first event. The link resolving and "
            "the file appearing in a listing prove nothing -- both go through stat(), which keeps "
            "succeeding while open() is denied.\n"
        )
        if any(under_documents(target) for _, target, _ in unreadable):
            out.write(
                "hook import smoke: the target sits under ~/Documents, so the likely cause is "
                "macOS TCC. Grant Full Disk Access to the program running this "
                "(System Settings -> Privacy & Security -> Full Disk Access) and rerun.\n"
            )
        return 1
    if failures:
        out.write(
            "hook import smoke: those scripts cannot load their shared modules, so the hooks "
            "they back never run. Check that install.sh links every shared directory they import.\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
