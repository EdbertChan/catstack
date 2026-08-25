"""Decide whether catstack itself (this repo) has uncommitted/unpushed
changes worth turning into a PR, and when to tell the agent to do it.

Read-only git only. This module must never shell out to a git subcommand
that writes state (commit/push/checkout -b/branch -d/reset --hard/...) --
see tests/test_hooks.py::test_detect_source_has_no_git_write_verbs, which
greps this file's own source for that. The hook only detects and signals;
the agent (via the draft-pr flow) does the actual PR work.

Claude has no true end-of-session hook -- only `Stop`, which fires after
every turn, including mid-edit turns. Firing immediately there would mean
opening a PR against half-written code almost every turn. So the Claude
path debounces: it hashes the relevant diff on every `Stop`; if the hash
changed since the last `Stop`, something is still being edited, stay
silent; if it's identical to last time, that's the first stable/idle point
and we deliver once. Cursor has a real `sessionEnd` event, so it needs no
debounce -- `stop` (mid-turn) stays silent unconditionally, `sessionEnd`
delivers once. Fail-open throughout: any git/subprocess error means no hit.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys

# Resolved via realpath (not abspath) so this always points at the one real
# catstack checkout even when this file is only reached through the
# ~/.claude/hooks/auto-pr or ~/.cursor/hooks/auto-pr symlink install.sh
# creates -- install.sh only ever symlinks hook directories, never copies
# them, so this is a structural guarantee, not a runtime guess.
HERE = os.path.dirname(os.path.realpath(__file__))
OWN_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))

STATE_DIR = os.environ.get(
    "AUTO_PR_STATE_DIR",
    os.path.join(os.path.expanduser("~"), ".cache", "catstack-auto-pr"),
)

RELEVANT_PREFIXES = ("engine/hooks/", "engine/skills/", "corpus/skills/", "product/skills/", "cursor/", "commands/", "always-on/", "docs/", "scripts/", ".github/workflows/")
RELEVANT_FILES = ("install.sh", "CLAUDE.md", "CONTRIBUTING.md")

INSTRUCTION = (
    "catstack changes detected on branch `{branch}` ({paths}, diff {digest}). "
    "Before finishing: "
    "(1) run `gh pr list --head {branch} --state open --json number,url` -- if one is "
    "already open, push to that branch instead of opening a new one; "
    "(2) if the diff mixes independent review claims, apply split-scope first; "
    "(3) for every touched engine/hooks/<name>/ that has a detect.py, verify or add a positive "
    "test (repro the bad case detect.py exists to catch, assert it fires) and a negative "
    "test (a clean case, assert it stays silent), then run "
    "`python3 scripts/check_hook_test_coverage.py engine/hooks/<name>` to confirm; "
    "(4) run that hook's real test suite and paste the real output into Test Plan; "
    "(5) use draft-pr's schema in its documented headless/non-interactive mode -- skip "
    "Scope & Ambiguity and Safety Invariant confirmation, record best-effort choices under "
    "Assumptions:, and prefix the PR title with [auto]; "
    "(6) push and open the PR with `gh pr create`. "
    "Do not ask for confirmation first -- this flow is pre-approved."
)


def _run_git(root: str, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", root, *args],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def repo_root(payload: dict) -> str | None:
    """The catstack checkout root, only if the session's cwd is inside it."""
    cwd = payload.get("cwd") or payload.get("workspace_roots")
    if isinstance(cwd, list):
        cwd = cwd[0] if cwd else ""
    if not isinstance(cwd, str) or not cwd:
        return None
    out = _run_git(cwd, "rev-parse", "--show-toplevel")
    if not out:
        return None
    try:
        candidate = os.path.realpath(out.strip())
    except OSError:
        return None
    if candidate != OWN_REPO_ROOT:
        return None
    return candidate


def current_branch(root: str) -> str:
    out = _run_git(root, "branch", "--show-current")
    return (out or "").strip() or "HEAD"


def _default_branch(root: str) -> str:
    out = _run_git(root, "symbolic-ref", "refs/remotes/origin/HEAD")
    if out and "/" in out:
        return out.strip().rsplit("/", 1)[-1]
    return "main"


def _changed_paths(root: str) -> list[str]:
    paths: set[str] = set()
    status = _run_git(root, "status", "--porcelain")
    if status:
        for line in status.splitlines():
            entry = line[3:].strip() if len(line) > 3 else ""
            if " -> " in entry:
                entry = entry.split(" -> ", 1)[1]
            if entry:
                paths.add(entry)
    branch = current_branch(root)
    default = _default_branch(root)
    if branch and branch != default:
        merge_base = _run_git(root, "merge-base", f"origin/{default}", "HEAD")
        if merge_base:
            diff = _run_git(root, "diff", "--name-only", merge_base.strip(), "HEAD")
            if diff:
                paths.update(p for p in diff.splitlines() if p)
    return sorted(paths)


def _is_relevant(path: str) -> bool:
    if path.startswith(".worktrees/") or "__pycache__" in path:
        return False
    if path in RELEVANT_FILES:
        return True
    return path.startswith(RELEVANT_PREFIXES)


def relevant_paths_changed(root: str) -> list[str]:
    return [p for p in _changed_paths(root) if _is_relevant(p)]


def diff_hash(root: str) -> str | None:
    status = _run_git(root, "status", "--porcelain")
    diff = _run_git(root, "diff", "HEAD")
    if status is None and diff is None:
        return None
    content = (status or "") + "\x00" + (diff or "")
    return hashlib.sha1(content.encode("utf-8", errors="replace")).hexdigest()[:16]


def _key(root: str, branch: str) -> str:
    return hashlib.sha1(f"{root}|{branch}".encode()).hexdigest()[:16]


def _last_hash_path(key: str) -> str:
    return os.path.join(STATE_DIR, f"{key}.last")


def _prompted_path(key: str, digest: str) -> str:
    return os.path.join(STATE_DIR, f"{key}.{digest}.prompted")


def read_last_hash(key: str) -> str | None:
    try:
        with open(_last_hash_path(key), encoding="utf-8") as handle:
            value = handle.read().strip()
    except OSError:
        return None
    return value or None


def write_last_hash(key: str, digest: str) -> None:
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(_last_hash_path(key), "w", encoding="utf-8") as handle:
            handle.write(digest)
    except OSError:
        pass


def already_prompted(key: str, digest: str) -> bool:
    return os.path.isfile(_prompted_path(key, digest))


def mark_prompted(key: str, digest: str) -> None:
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(_prompted_path(key, digest), "w", encoding="utf-8") as handle:
            handle.write(digest)
    except OSError:
        pass


def wants_interrupt(payload: dict, argv: list[str] | None = None) -> bool:
    """True only for a real end-of-session event (Cursor sessionEnd)."""
    args = [str(item).lower() for item in (argv if argv is not None else sys.argv[1:])]
    if any(item in {"sessionend", "session_end"} for item in args):
        return True
    event = str(
        payload.get("hook_event_name")
        or payload.get("hookEventName")
        or payload.get("event")
        or payload.get("type")
        or ""
    ).lower()
    return event in {"sessionend", "session_end"}


def decide(
    payload: dict,
    *,
    argv: list[str] | None = None,
    deliver: bool | None = None,
    debounce: bool = False,
) -> str | None:
    """Return the follow-up instruction, or None to stay silent.

    `deliver=True` (Cursor sessionEnd, or forced by the caller): deliver
    immediately, once per diff hash. `deliver=False`/`debounce=True`
    (Claude Stop): deliver only once the diff hash is unchanged from the
    previous Stop call. `deliver=False`/`debounce=False` (Cursor mid-turn
    `stop`): always silent, no state written -- sessionEnd is Cursor's only
    delivery path.
    """
    if payload.get("stop_hook_active"):
        return None
    root = repo_root(payload)
    if not root:
        return None
    paths = relevant_paths_changed(root)
    if not paths:
        return None
    digest = diff_hash(root)
    if not digest:
        return None
    branch = current_branch(root)
    key = _key(root, branch)

    should_deliver = wants_interrupt(payload, argv) if deliver is None else deliver

    if should_deliver:
        if already_prompted(key, digest):
            return None
        mark_prompted(key, digest)
        return INSTRUCTION.format(branch=branch, paths=", ".join(paths[:8]), digest=digest)

    if not debounce:
        return None

    last = read_last_hash(key)
    write_last_hash(key, digest)
    if last == digest and not already_prompted(key, digest):
        mark_prompted(key, digest)
        return INSTRUCTION.format(branch=branch, paths=", ".join(paths[:8]), digest=digest)
    return None
