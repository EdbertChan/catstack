"""hook-freshness: the installed hooks are only as new as the checkout behind them.

`install.sh` symlinks `~/.claude/hooks/<name>` at a catstack checkout, so a
hook fix that is merged on `origin/main` does nothing on this machine while
that checkout sits on a feature branch or behind the remote. This resolves
the checkout from the `diu-stop` symlink, reads its branch and its distance
from `origin/main`, and returns one advisory line for the turn.

Advisory only: no block, no LLM, no network unless
CATSTACK_HOOK_FRESHNESS_FETCH=1. Fails open on every error.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess

STATE_DIR = os.environ.get(
    "HOOK_FRESHNESS_STATE_DIR",
    os.path.join(os.path.expanduser("~"), ".cache", "catstack-hook-freshness"),
)

ANCHOR_LINK = os.path.join(os.path.expanduser("~"), ".claude", "hooks", "diu-stop")
TRUNK = "origin/main"
FETCH_TIMEOUT_SECS = 3
GIT_TIMEOUT_SECS = 5

MESSAGE = (
    "catstack hooks are stale: the checkout behind ~/.claude/hooks is {detail}. "
    "Merged hook and skill fixes are not live here until it is updated. Run "
    "`git -C {repo} pull --ff-only` (or merge {trunk} into the branch), then "
    "`{repo}/install.sh`, and restart the harness."
)


def _run_git(args, cwd, timeout=GIT_TIMEOUT_SECS):
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def resolve_repo(env=None, realpath=os.path.realpath, isdir=os.path.isdir):
    """The catstack checkout the live hooks point at, or None."""
    env = env if env is not None else os.environ
    override = env.get("CATSTACK_HOOKS_REPO")
    if override:
        return override if isdir(os.path.join(override, ".git")) else None
    try:
        target = realpath(ANCHOR_LINK)
    except OSError:
        return None
    repo = os.path.dirname(os.path.dirname(os.path.dirname(target)))
    return repo if isdir(os.path.join(repo, ".git")) else None


def repo_state(repo, env=None, run=_run_git):
    """(branch, commits behind trunk) for the checkout, or (None, None)."""
    env = env if env is not None else os.environ
    try:
        if env.get("CATSTACK_HOOK_FRESHNESS_FETCH") == "1":
            run(["fetch", "--quiet", "origin", "main"], repo, FETCH_TIMEOUT_SECS)
        branch = run(["branch", "--show-current"], repo)
        behind_raw = run(["rev-list", "--count", f"HEAD..{TRUNK}"], repo)
    except (OSError, subprocess.SubprocessError):
        return None, None
    if behind_raw is None:
        return branch, None
    try:
        return branch, int(behind_raw)
    except ValueError:
        return branch, None


def advisory(repo, branch, behind):
    """One line when the checkout is off trunk or behind it, else None."""
    if not repo or behind is None:
        return None
    off_trunk = bool(branch) and branch != "main"
    if not off_trunk and behind <= 0:
        return None
    parts = []
    if off_trunk:
        parts.append(f"on branch `{branch}`")
    if behind > 0:
        commit_word = "commit" if behind == 1 else "commits"
        parts.append(f"{behind} {commit_word} behind {TRUNK}")
    return MESSAGE.format(detail=" and ".join(parts), repo=repo, trunk=TRUNK)


def _state_file(key):
    digest = hashlib.sha256((key or "no-transcript").encode("utf-8")).hexdigest()[:16]
    return os.path.join(STATE_DIR, f"{digest}.advised")


def already_advised(key):
    return os.path.isfile(_state_file(key))


def mark_advised(key):
    path = _state_file(key)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write((key or "") + "\n")
    except OSError:
        pass


def decide(payload, env=None, run=_run_git, state=True):
    """Advisory context for this prompt, or None. Once per session."""
    env = env if env is not None else os.environ
    if env.get("CATSTACK_HOOK_FRESHNESS") == "0":
        return None
    key = payload.get("transcript_path") or payload.get("transcriptPath") or ""
    if state and already_advised(key):
        return None
    repo = resolve_repo(env=env)
    if not repo:
        return None
    branch, behind = repo_state(repo, env=env, run=run)
    line = advisory(repo, branch, behind)
    if line and state:
        mark_advised(key)
    return line


def decide_json(payload, env=None, run=_run_git, state=True):
    line = decide(payload, env=env, run=run, state=state)
    if not line:
        return None
    return json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": line,
        }
    })
