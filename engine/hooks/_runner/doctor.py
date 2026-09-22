#!/usr/bin/env python3
"""Ask whether the installed hooks can run, from where they are installed.

`install.sh` ends by checking its own work, and the standalone form of that
same check is this file: run it any time to find out whether the hooks are
healthy right now, without reinstalling anything. It is read-only apart from
one probe run whose metrics go to a temporary directory.

    python3 ~/.claude/hooks/_runner/doctor.py

It lives beside the runner rather than in the checkout's script directory so
that the standalone form keeps working when the checkout does not: the hooks
directory is what a harness reaches for on every event, so a doctor installed
with the hooks is reachable exactly when the hooks are.

Four checks, in the order a hook event travels:

  1. `runner`     -- the runner each harness command names can be opened.
  2. `hooks`      -- every installed hook entry script can be opened and
                     imported. Opened first: a link can resolve, `stat()` can
                     succeed, and `open()` can still fail -- a dangling target,
                     an unreadable mode, or a macOS TCC denial on a checkout
                     under `~/Documents`. Existence tests go through `stat()`,
                     so they pass for the whole of such a denial while every
                     real hook run dies.
  3. `end-to-end` -- one real run through the runner, of a probe hook that
                     ships next to it, proving the chain a harness uses:
                     resolve the script under the installed hooks root, feed it
                     stdin, hand back its stdout, record a metrics row. The
                     probe stands in for a real hook so the run does not write
                     any real hook's state into the user's session.
  4. `effective`  -- the installed links point at this checkout, delegated to
                     the repository's own checker when the checkout is
                     reachable.

Every check reports one of three outcomes, never two: `pass`, `fail`, or
`unchecked`. A check that could not look at its subject -- no harness
directory, a checker that is not on disk -- says so and the run exits non-zero
(Saltzer & Schroeder 1975, https://web.mit.edu/Saltzer/www/publications/protection/Basic.html:
base access decisions on permission rather than exclusion, so a missing answer
is never read as a clean one).

Exit 0: every check passed. Exit 1: a check failed. Exit 2: nothing failed but
something could not be checked.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import tempfile

HARNESS_DIRS = (".claude", ".cursor", ".codex")
SKIP_PREFIXES = ("install_", "test_")
SKIP_NAMES = ("detect.py", "state.py")
DEFAULT_TIMEOUT = 5.0
PROBE_TIMEOUT = 20.0
IMPORT_FAIL_EXIT = 97
UNREADABLE_EXIT = 96
PROBE_MARKER = "catstack-hook-doctor: probe reached"
PROBE_SCRIPT = "_runner/probe_hook.py"
DOCUMENTS = os.path.expanduser("~/Documents")
TCC_HINT = (
    "the target sits under ~/Documents, so the likely cause is macOS TCC. Grant Full Disk "
    "Access to the program running this (System Settings -> Privacy & Security -> Full Disk "
    "Access) and rerun."
)

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


class Result:
    """One check's outcome plus the lines a reader needs to act on it."""

    def __init__(self, name: str, status: str, lines: list[str]):
        self.name = name
        self.status = status
        self.lines = lines


def installed_harnesses(home: str) -> list[str]:
    return [h for h in HARNESS_DIRS if os.path.isdir(os.path.join(home, h, "hooks"))]


def entry_scripts(home: str) -> list[str]:
    """Every installed hook entry script, in a stable order.

    Shared-module directories (`_sdk`, `_runner`, ...) are libraries, and
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


def _last_stderr_line(result) -> str:
    lines = (result.stderr or "").strip().splitlines()
    return lines[-1] if lines else f"exit={result.returncode}, no stderr"


def classify(path: str, timeout: float, run=subprocess.run) -> tuple[str, str]:
    """(outcome, detail) for one script: ok, unreadable, import-fail, or slow.

    The child opens the file before importing anything, so `unreadable` beats
    `import-fail` whenever both would apply: the more specific cause is the one
    reported. A timeout is not a failure -- imports resolve before a module
    reaches whatever it is still doing.
    """
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


def check_runner(home: str, run=subprocess.run) -> Result:
    """Every installed harness has a runner its commands can open."""
    harnesses = installed_harnesses(home)
    if not harnesses:
        return Result("runner", "unchecked", [f"no harness hooks directory under {home}"])
    lines: list[str] = []
    status = "pass"
    for harness in harnesses:
        path = os.path.join(home, harness, "hooks", "_runner", "run.py")
        try:
            with open(path, "rb") as handle:
                handle.read(1)
        except OSError as exc:
            status = "fail"
            lines.append(f"{harness}: {type(exc).__name__}: {exc}")
            continue
        lines.append(f"{harness}: {os.path.relpath(path, home)}")
    return Result("runner", status, lines)


def check_hooks(home: str, timeout: float = DEFAULT_TIMEOUT, run=subprocess.run) -> Result:
    """Every installed hook entry script opens and imports."""
    scripts = entry_scripts(home)
    if not scripts:
        return Result(
            "hooks",
            "unchecked",
            [
                f"no hook scripts found under {home}; the hooks directories are missing or "
                "unreadable, so nothing was verified"
            ],
        )
    unreadable: list[str] = []
    failures: list[str] = []
    slow: list[str] = []
    for path in scripts:
        outcome, detail = classify(path, timeout, run=run)
        shown = os.path.relpath(path, home)
        if outcome == "unreadable":
            unreadable.append(f"{shown} -> {os.path.realpath(path)}: {detail}")
        elif outcome == "import-fail":
            failures.append(f"{shown}: {detail}")
        elif outcome == "slow":
            slow.append(f"{shown}: {detail} (imports resolved; still working)")
    lines = [
        f"checked={len(scripts)} unreadable={len(unreadable)} "
        f"import-fail={len(failures)} slow={len(slow)}"
    ]
    lines.extend(unreadable + failures + slow)
    if unreadable:
        lines.append(
            "those scripts exist but cannot be opened by the interpreter that runs them, so "
            "every hook they back dies on its first event"
        )
        if any(f" -> {DOCUMENTS}/" in line for line in unreadable):
            lines.append(TCC_HINT)
    if failures:
        lines.append(
            "those scripts cannot load their shared modules; check that install.sh links every "
            "shared directory they import"
        )
    return Result("hooks", "fail" if unreadable or failures else "pass", lines)


def check_end_to_end(home: str, run=subprocess.run) -> Result:
    """One real run of the probe hook through each harness's own runner."""
    harnesses = installed_harnesses(home)
    if not harnesses:
        return Result("end-to-end", "unchecked", [f"no harness hooks directory under {home}"])
    lines: list[str] = []
    status = "pass"
    payload = json.dumps(
        {"hook_event_name": "UserPromptSubmit", "session_id": "hook-doctor", "prompt": "hook-doctor"}
    )
    for harness in harnesses:
        runner = os.path.join(home, harness, "hooks", "_runner", "run.py")
        probe = os.path.join(home, harness, "hooks", PROBE_SCRIPT)
        if not os.path.exists(probe):
            status = "fail" if status != "fail" else status
            lines.append(f"{harness}: no probe hook at {os.path.relpath(probe, home)}")
            continue
        with tempfile.TemporaryDirectory(prefix="catstack-hook-doctor-") as metrics_dir:
            env = dict(os.environ, CATSTACK_HOOK_METRICS_DIR=metrics_dir)
            try:
                result = run(
                    [sys.executable, runner, "--timeout", "10", PROBE_SCRIPT],
                    input=payload,
                    capture_output=True,
                    text=True,
                    timeout=PROBE_TIMEOUT,
                    env=env,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                status = "fail"
                lines.append(f"{harness}: the runner did not finish within {PROBE_TIMEOUT:g}s")
                continue
            except OSError as exc:
                status = "fail"
                lines.append(f"{harness}: could not start the runner: {type(exc).__name__}: {exc}")
                continue
            rows, metrics_error = _metrics_rows(os.path.join(metrics_dir, "runs.jsonl"))
        problems = _probe_problems(result, rows, metrics_error)
        if problems:
            status = "fail"
            lines.extend(f"{harness}: {problem}" for problem in problems)
        else:
            lines.append(f"{harness}: exit=0, marker returned, metrics row written")
    return Result("end-to-end", status, lines)


def _metrics_rows(path: str) -> tuple[list[dict], str]:
    """(rows, why the log could not be read).

    A log this cannot read is reported as its own problem rather than folded
    into "no rows": an unreadable log and an unwritten one are different
    defects, and reading one as the other sends the reader to the wrong place.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()], ""
    except FileNotFoundError:
        return [], ""
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [], f"could not read the metrics log {path}: {type(exc).__name__}: {exc}"


def _probe_problems(result, rows: list[dict], metrics_error: str) -> list[str]:
    """What the probe run got wrong, in the order a reader should read it."""
    problems: list[str] = []
    if result.returncode != 0:
        tail = (result.stderr or "").strip().splitlines()
        problems.append(f"the runner exited {result.returncode}" + (f": {tail[-1]}" if tail else ""))
    if PROBE_MARKER not in (result.stdout or ""):
        problems.append("the probe's output did not come back through the runner")
    if metrics_error:
        problems.append(metrics_error)
    elif not rows:
        problems.append("the runner wrote no metrics row, so hook failures would go unreported")
    return problems


def check_effective(run=subprocess.run) -> Result:
    """Delegate to the repository's own drift checker when it is reachable."""
    checker = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))),
        "scripts",
        "ci",
        "check_install_effective.py",
    )
    if not os.path.exists(checker):
        return Result(
            "effective",
            "unchecked",
            [f"no drift checker at {checker}; the checkout this was installed from is not reachable"],
        )
    try:
        result = run([sys.executable, checker], capture_output=True, text=True, check=False)
    except OSError as exc:
        return Result("effective", "unchecked", [f"could not run the drift checker: {exc}"])
    lines = [line for line in (result.stdout or "").splitlines() if line.strip()]
    lines.extend(line for line in (result.stderr or "").splitlines() if line.strip())
    return Result("effective", "pass" if result.returncode == 0 else "fail", lines or ["no output"])


def run_checks(home: str, timeout: float = DEFAULT_TIMEOUT, run=subprocess.run) -> list[Result]:
    return [
        check_runner(home, run=run),
        check_hooks(home, timeout=timeout, run=run),
        check_end_to_end(home, run=run),
        check_effective(run=run),
    ]


def report(results: list[Result], out) -> int:
    for index, result in enumerate(results, start=1):
        out.write(f"[{index}/{len(results)}] {result.name}\n")
        for line in result.lines:
            out.write(f"        {line}\n")
        out.write(f"{result.status.upper():<9}{result.name}\n")
    counts = {status: sum(1 for r in results if r.status == status) for status in ("pass", "fail", "unchecked")}
    out.write(
        f"hook doctor: {counts['pass']} pass, {counts['fail']} fail, "
        f"{counts['unchecked']} unchecked\n"
    )
    if counts["fail"]:
        return 1
    if counts["unchecked"]:
        return 2
    return 0


def main(argv: list[str] | None = None, stdout=None, run=subprocess.run) -> int:
    parser = argparse.ArgumentParser(description="Check that the installed hooks can run.")
    parser.add_argument("--home", default=os.path.expanduser("~"))
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    args = parser.parse_args(argv)
    out = stdout or sys.stdout
    return report(run_checks(args.home, timeout=args.timeout, run=run), out)


if __name__ == "__main__":
    raise SystemExit(main())
