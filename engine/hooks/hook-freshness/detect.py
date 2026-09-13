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


SETTINGS_PATH = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")

UNCHECKED_MESSAGE = (
    "hook-freshness: could not check whether the registered hook scripts resolve, because "
    "{reason}. Treat the hook set as unchecked rather than healthy."
)

UNRESOLVABLE_MESSAGE = (
    "hook-freshness: {count} registered hook script(s) cannot run because their path does "
    "not resolve: {paths}. Those hooks are unchecked, not clean — a gate that never "
    "executes reports nothing. Re-run your catstack `install.sh` to relink them."
)


def _load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _hook_commands(settings_path=SETTINGS_PATH, load=None):
    """(commands, unreadable_reason). A reason means the sweep could not run at all."""
    loader = load or _load_json
    try:
        data = loader(settings_path)
    except FileNotFoundError:
        return [], f"{settings_path} does not exist"
    except (OSError, ValueError) as exc:
        return [], f"{settings_path} could not be read ({type(exc).__name__}: {exc})"
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return [], f"{settings_path} has no readable 'hooks' object"
    commands = []
    malformed = 0
    for matchers in hooks.values():
        if not isinstance(matchers, list):
            malformed += 1
            continue
        for matcher in matchers:
            if not isinstance(matcher, dict):
                malformed += 1
                continue
            for entry in matcher.get("hooks") or []:
                if isinstance(entry, dict) and entry.get("command"):
                    commands.append(str(entry["command"]))
                else:
                    malformed += 1
    if malformed and not commands:
        return [], f"{settings_path} has {malformed} hook entr(ies) in an unrecognised shape and no readable command"
    return commands, None


def _script_paths(command):
    expanded = os.path.expandvars(command).replace("~/", os.path.expanduser("~") + "/")
    return [tok for tok in expanded.split() if "/" in tok and not tok.startswith("-")]


def unresolvable_hooks(settings_path=SETTINGS_PATH, load=None, exists=os.path.exists):
    """(missing script paths, unreadable_reason). Never reports clean when it could not look."""
    commands, unreadable = _hook_commands(settings_path, load=load)
    if unreadable:
        return [], unreadable
    missing = []
    for command in commands:
        for path in _script_paths(command):
            if "$" in path:
                continue
            if not exists(path) and path not in missing:
                missing.append(path)
    return missing, None


def unresolvable_advisory(missing, unreadable=None):
    if unreadable:
        return UNCHECKED_MESSAGE.format(reason=unreadable)
    if not missing:
        return None
    shown = ", ".join(missing[:3])
    if len(missing) > 3:
        shown += f", and {len(missing) - 3} more"
    return UNRESOLVABLE_MESSAGE.format(count=len(missing), paths=shown)


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
    missing, unreadable = unresolvable_hooks()
    lines = [ln for ln in [unresolvable_advisory(missing, unreadable)] if ln]
    repo = resolve_repo(env=env)
    if repo:
        branch, behind = repo_state(repo, env=env, run=run)
        staleness = advisory(repo, branch, behind)
        if staleness:
            lines.append(staleness)
    if not lines:
        return None
    line = "\n".join(lines)
    if state:
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
