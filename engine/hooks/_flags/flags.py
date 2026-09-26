#!/usr/bin/env python3
"""One definition of "is this catstack flag on", shared by every flagged hook.

A flag is off unless something turns it on. The value is looked up in this
order, and the first source that defines the key wins:

  1. the process environment
  2. the file named by `$CATSTACK_ENV_FILE`, if that variable is set
  3. `<repo root>/.env`, for the repo containing the hook's `cwd`
  4. `~/.catstack.env`

Files are parsed as plain `KEY=VALUE` lines. They are never sourced, and no
key other than the one asked for is read back or printed.

Three outcomes, not two. A lookup answers set-on, set-off, or could-not-tell,
and they are different answers:

  * `FlagLookup.value is None` -- nothing defined the key. Unset, not off.
  * `FlagLookup.unreadable` -- a candidate file exists and could not be read
    or decoded. The flag may well be set in there. A caller that treats this
    as a clean "not set" is doing exactly what "a check that could not run is
    not a pass" forbids, so `flag_on` returning False is never the whole
    story: `unreadable` is non-empty and the caller has to say so.

`flag_on` collapses the lookup to a bool for the common path and fails closed
-- an unreadable file leaves an opt-in flag off. That is the safe direction
for these hooks (an advisory that stays quiet), but it is a decision, not an
accident, and it is why the note has to reach the user some other way.

Why a module and not a copy of the reader in each hook: cat-mode-default
grew this lookup first, and the reflect/automate-me hooks need exactly the
same one. Two readers over the same files drift apart silently -- one learns
about `~/.catstack.env` and the other does not, and the user who sets the
flag in one place finds half the hooks still running.

Hooks are installed as sibling symlinks under $HOME/.claude/hooks/, so a
hook reaches this module by its own parent directory:

    sys.path.insert(0, os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_flags"))

Two dirnames, not a "..": the hook's own directory is a symlink, so the OS
resolves it before applying "..", landing beside the checkout instead of
beside the other hooks. Stripping two segments textually cannot do that, and
abspath (never realpath) is what keeps the installed path in place.
"""
from __future__ import annotations

import os
import re
import sys
from typing import NamedTuple

ENV_FILE_VAR = "CATSTACK_ENV_FILE"
HOME_ENV_FILE = "~/.catstack.env"
TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
ENV_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")

REFLECT_ENFORCEMENT = "CATSTACK_REFLECT_ENFORCEMENT"
HOOK_DISPATCHER = "CATSTACK_HOOK_DISPATCHER"


class UnreadableEnvFile(Exception):
    """A candidate .env file exists but could not be read or decoded."""

    def __init__(self, path: str, reason: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.path = path
        self.reason = reason


class FlagLookup(NamedTuple):
    value: str | None
    source: str | None
    unreadable: tuple[tuple[str, str], ...] = ()

    @property
    def on(self) -> bool:
        return self.value is not None and self.value.strip().lower() in TRUE_VALUES

    def unreadable_note(self, key: str) -> str:
        """One line naming the files that could not be checked, or "" when
        every candidate was readable. Callers print this instead of letting an
        unreadable file pass as "flag not set"."""
        if not self.unreadable:
            return ""
        listed = "; ".join(f"{path} ({reason})" for path, reason in self.unreadable)
        return (
            f"catstack: could not read {listed} while looking up {key}. "
            f"Treating {key} as off -- set it in the environment to be sure."
        )


def repo_root(start: str | None) -> str | None:
    """The nearest ancestor of `start` holding a `.git`, or None.

    None means "no repo to look in" -- either no cwd was supplied or the walk
    reached the filesystem root. Both are ordinary: the caller drops the
    `<repo root>/.env` candidate and keeps the others. This is not a read
    failure, which is what `UnreadableEnvFile` is for.
    """
    if not start:
        return None
    current = os.path.abspath(start)
    while True:
        if os.path.exists(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def env_file_candidates(environ: dict, cwd: str | None, home: str | None = None) -> list[str]:
    candidates: list[str] = []
    explicit = environ.get(ENV_FILE_VAR)
    if explicit:
        candidates.append(os.path.expanduser(explicit))
    root = repo_root(cwd)
    if root:
        candidates.append(os.path.join(root, ".env"))
    home_dir = home or environ.get("HOME") or os.path.expanduser("~")
    candidates.append(os.path.join(home_dir, HOME_ENV_FILE.replace("~/", "", 1)))
    return candidates


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def read_flag_from_file(path: str, key: str) -> str | None:
    """Return the value of `key` from a KEY=VALUE file.

    None means the file is not there, or is there and does not define the key
    -- both are honest "not set here" answers. A file that exists and cannot
    be read or decoded raises `UnreadableEnvFile` rather than returning None,
    because "I could not look" and "I looked and it is absent" are different
    answers and only the second one is a clean miss.

    A later line for the same key wins, as a shell would. Blank lines and
    `#` comments define nothing and are skipped; that is the file format, not
    a parse failure.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        raise UnreadableEnvFile(path, type(exc).__name__) from exc
    found: str | None = None
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = ENV_LINE_RE.match(raw)
        if match and match.group(1) == key:
            found = _unquote(match.group(2))
    return found


def resolve_flag(
    key: str, environ: dict, cwd: str | None, home: str | None = None
) -> FlagLookup:
    """Look `key` up across every source. `source` is "env" or the path of the
    file that defined it; `value` is None when nothing did. Files that exist
    but could not be read land in `unreadable` and do not stop the walk -- a
    later candidate may still define the key."""
    if key in environ:
        return FlagLookup(environ[key], "env")
    unreadable: list[tuple[str, str]] = []
    for path in env_file_candidates(environ, cwd, home):
        try:
            value = read_flag_from_file(path, key)
        except UnreadableEnvFile as exc:
            unreadable.append((exc.path, exc.reason))
            continue
        if value is not None:
            return FlagLookup(value, path, tuple(unreadable))
    return FlagLookup(None, None, tuple(unreadable))


def flag_on(key: str, environ: dict, cwd: str | None, home: str | None = None) -> bool:
    """True only when a source says so. Fails closed: an unreadable candidate
    file leaves the flag off. Use `resolve_flag` when you need to tell the
    user that a file could not be checked."""
    return resolve_flag(key, environ, cwd, home).on


def reflect_enforcement(environ: dict, cwd: str | None, home: str | None = None) -> FlagLookup:
    """Full lookup for the reflect/automate-me flag, so a caller can report an
    unreadable candidate file instead of silently staying quiet.

    The key is defined once, here beside the reader, because several hooks
    answer to it and a key spelled from memory in one of them is a hook that
    never turns on. Off unless a source sets it: these hooks push the user
    into /reflect and automate-me, up to stopping every tool, so opting in is
    the user's call.
    """
    return resolve_flag(REFLECT_ENFORCEMENT, environ, cwd, home)


def reflect_enforcement_on(environ: dict, cwd: str | None, home: str | None = None) -> bool:
    return reflect_enforcement(environ, cwd, home).on


def hook_dispatcher(environ: dict, cwd: str | None, home: str | None = None) -> FlagLookup:
    """Full lookup for the per-event hook dispatcher flag.

    Off unless a source sets it: `wrap_installed.py` reads this at install
    time to decide whether a harness event gets one settings entry per hook
    (today's layout) or one entry that calls `_runner/dispatch.py` for the
    whole event. Same three-outcome shape as `reflect_enforcement` -- an
    unreadable candidate file is not read as "not set".
    """
    return resolve_flag(HOOK_DISPATCHER, environ, cwd, home)


def hook_dispatcher_on(environ: dict, cwd: str | None, home: str | None = None) -> bool:
    return hook_dispatcher(environ, cwd, home).on


def enforcement_gate(
    hook_name: str,
    cwd: str | None,
    environ: dict | None = None,
    stderr=None,
) -> bool:
    """The one gate every reflect/automate-me hook calls.

    True only when the user opted in. A candidate .env file that exists and
    could not be read is named on stderr first, because the honest answer
    there is "I could not check", and a hook that just went quiet would be
    reporting that as "the user did not opt in".

    `cwd` comes from the hook payload; it is what lets one repo turn the
    class on through its own `.env`. None is fine -- the process environment
    and `~/.catstack.env` are still consulted.
    """
    found = reflect_enforcement(os.environ if environ is None else environ, cwd)
    note = found.unreadable_note(REFLECT_ENFORCEMENT)
    if note:
        (stderr or sys.stderr).write(f"{hook_name}: {note}\n")
    return found.on


def main(argv: list[str] | None = None, environ: dict | None = None, stdout=None, stderr=None) -> int:
    """Print `on`, `off`, or `unchecked` for one key, for callers that are not
    Python. install.sh reads it to pick which always-on rules to install.
    `unchecked` means a candidate file could not be read: the note goes to
    stderr and the caller treats the flag as off, like the hooks do.

    `--value` prints the raw value instead, lowercased and trimmed, for a flag
    with more than two settings. Unset prints an empty line; unreadable still
    prints `unchecked`."""
    import argparse

    parser = argparse.ArgumentParser(description="Look up one catstack flag.")
    parser.add_argument("key")
    parser.add_argument("--cwd", default=None, help="where to start looking for a repo .env")
    parser.add_argument("--value", action="store_true", help="print the raw value, not on/off")
    args = parser.parse_args(argv)
    found = resolve_flag(args.key, dict(os.environ if environ is None else environ), args.cwd)
    note = found.unreadable_note(args.key)
    if note:
        (stderr or sys.stderr).write(note + "\n")
    if args.value:
        raw = "unchecked" if found.value is None and note else (found.value or "").strip().lower()
        (stdout or sys.stdout).write(raw + "\n")
        return 0
    state = "on" if found.on else ("unchecked" if note else "off")
    (stdout or sys.stdout).write(state + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
