"""hook-freshness: the installed hooks are only as new as the checkout behind them.

`install.sh` symlinks `~/.claude/hooks/<name>` at a catstack checkout, so a
hook fix that is merged on `origin/main` does nothing on this machine while
that checkout sits on a feature branch or behind the remote. This resolves
the checkout from the `diu-stop` symlink, reads its branch and its distance
from `origin/main`, and returns one advisory line for the turn.

Advisory only: no block, no LLM, no network unless
CATSTACK_HOOK_FRESHNESS=fetch. Fails open on every error.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys

SDK_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "_sdk")
if SDK_DIR not in sys.path:
    sys.path.insert(0, SDK_DIR)

from finding import Finding

STATE_DIR = os.environ.get(
    "HOOK_FRESHNESS_STATE_DIR",
    os.path.join(os.path.expanduser("~"), ".cache", "catstack-hook-freshness"),
)

ANCHOR_LINK = os.path.join(os.path.expanduser("~"), ".claude", "hooks", "diu-stop")
TRUNK = "origin/main"
FETCH_TIMEOUT_SECS = 3

MODE_FLAG = "CATSTACK_HOOK_FRESHNESS"
RETIRED_FETCH_FLAG = "CATSTACK_HOOK_FRESHNESS_FETCH"
OFF_VALUES = frozenset({"off", "0", "false", "no"})
LOCAL_VALUES = frozenset({"", "local", "1", "true", "yes", "on"})
GIT_TIMEOUT_SECS = 5

MESSAGE = (
    "catstack hooks are stale: the checkout behind ~/.claude/hooks is {detail}. "
    "Merged hook and skill fixes are not live here until it is updated. Run "
    "`git -C {repo} pull --ff-only` (or merge {trunk} into the branch), then "
    "`{repo}/install.sh`, and restart the harness."
)

RULE_CONFIG = "hook-freshness.config"
RULE_UNCHECKED = "hook-freshness.unchecked-settings"
RULE_UNRESOLVABLE = "hook-freshness.unresolvable-script"
RULE_DELETED_INSTALLED = "hook-freshness.deleted-installed-hook"
RULE_STALE_CHECKOUT = "hook-freshness.stale-checkout"


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


def freshness_mode(env):
    """(mode, note). mode is off, local, or fetch; note names a value this
    hook could not use, or None."""
    raw = env.get(MODE_FLAG, "").strip().lower()
    notes = []
    if RETIRED_FETCH_FLAG in env:
        notes.append(
            f"hook-freshness: {RETIRED_FETCH_FLAG} is retired and ignored; "
            f"set {MODE_FLAG}=fetch instead."
        )
    if raw in OFF_VALUES:
        mode = "off"
    elif raw == "fetch":
        mode = "fetch"
    elif raw in LOCAL_VALUES:
        mode = "local"
    else:
        mode = "local"
        notes.append(
            f"hook-freshness: {MODE_FLAG}={env.get(MODE_FLAG)} is not off, local, or fetch; using local."
        )
    return mode, "\n".join(notes) or None


def repo_state(repo, env=None, run=_run_git):
    """(branch, commits behind trunk) for the checkout, or (None, None)."""
    env = env if env is not None else os.environ
    try:
        if freshness_mode(env)[0] == "fetch":
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

DELETED_INSTALLED_MESSAGE = (
    "hook-freshness: {count} installed hook folder no longer exists in the "
    "catstack checkout behind ~/.claude/hooks: {hooks}. Removed hooks can still "
    "shape this session while this install points at stale paths. Run "
    "`git -C {repo} pull --ff-only`, then `{repo}/install.sh`, and restart the harness."
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


def _hook_folders_from_commands(commands):
    folders = []
    for command in commands:
        for path in _script_paths(command):
            folder = os.path.basename(os.path.dirname(path))
            if not folder or folder.startswith("_"):
                continue
            if folder not in folders:
                folders.append(folder)
    return folders


def installed_hook_folders(settings_path=SETTINGS_PATH, load=None):
    commands, unreadable = _hook_commands(settings_path, load=load)
    if unreadable:
        return [], unreadable
    return _hook_folders_from_commands(commands), None


def deleted_installed_hook_folders(repo, settings_path=SETTINGS_PATH, load=None, exists=os.path.exists):
    folders, unreadable = installed_hook_folders(settings_path=settings_path, load=load)
    if unreadable or not repo:
        return [], unreadable
    missing = [
        folder for folder in folders
        if not exists(os.path.join(repo, "engine", "hooks", folder))
    ]
    return missing, None


RUNNER_SUFFIX = "/_runner/run.py"


def _script_paths(command):
    expanded = os.path.expandvars(command).replace("~/", os.path.expanduser("~") + "/")
    tokens = [tok for tok in expanded.split() if "/" in tok and not tok.startswith("-")]
    runner = next((tok for tok in tokens if os.path.isabs(tok) and tok.endswith(RUNNER_SUFFIX)), None)
    if runner is None:
        return tokens
    hooks_root = os.path.dirname(os.path.dirname(runner))
    return [tok if os.path.isabs(tok) else os.path.join(hooks_root, tok) for tok in tokens]


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


def deleted_installed_advisory(missing, repo):
    if not missing:
        return None
    shown = ", ".join(missing[:3])
    if len(missing) > 3:
        shown += f", and {len(missing) - 3} more"
    return DELETED_INSTALLED_MESSAGE.format(count=len(missing), hooks=shown, repo=repo)


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


def decide(
    payload,
    env=None,
    run=_run_git,
    state=True,
    settings_path=SETTINGS_PATH,
    load=None,
    exists=os.path.exists,
):
    """Advisory context for this prompt, or None. Once per session."""
    env = env if env is not None else os.environ
    mode, mode_note = freshness_mode(env)
    if mode == "off":
        return None
    key = payload.get("transcript_path") or payload.get("transcriptPath") or ""
    if state and already_advised(key):
        return None
    missing, unreadable = unresolvable_hooks(settings_path=settings_path, load=load, exists=exists)
    lines = [ln for ln in [mode_note, unresolvable_advisory(missing, unreadable)] if ln]
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


def decide_json(
    payload,
    env=None,
    run=_run_git,
    state=True,
    settings_path=SETTINGS_PATH,
    load=None,
    exists=os.path.exists,
):
    line = decide(
        payload,
        env=env,
        run=run,
        state=state,
        settings_path=settings_path,
        load=load,
        exists=exists,
    )
    if not line:
        return None
    return json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": line,
        }
    })


def detect(
    event,
    env=None,
    run=_run_git,
    state=True,
    settings_path=None,
    load=None,
    exists=os.path.exists,
):
    """Find stale or deleted installed hook conditions for the shared runtime."""
    env = env if env is not None else _event_env(event)
    mode, mode_note = freshness_mode(env)
    if mode == "off":
        return []
    key = event.get("transcript_path") or event.get("transcriptPath") or ""
    if state and already_advised(key):
        return []

    path = settings_path or _event_settings_path(event)
    findings = []
    if mode_note:
        findings.append(Finding(RULE_CONFIG, MODE_FLAG, mode_note, mode_note))

    repo = resolve_repo(env=env)
    deleted = []
    unreadable = None
    if repo:
        deleted, unreadable = deleted_installed_hook_folders(
            repo,
            settings_path=path,
            load=load,
            exists=exists,
        )
        deleted_message = deleted_installed_advisory(deleted, repo)
        if deleted_message:
            findings.append(
                Finding(
                    RULE_DELETED_INSTALLED,
                    ",".join(deleted),
                    deleted_message,
                    f"installed={','.join(deleted)} repo={repo}",
                )
            )

    missing, unresolvable_unreadable = unresolvable_hooks(settings_path=path, load=load, exists=exists)
    unreadable = unreadable or unresolvable_unreadable
    if unreadable:
        message = unresolvable_advisory([], unreadable)
        findings.append(Finding(RULE_UNCHECKED, path, message, unreadable))
    else:
        missing = _without_deleted_hook_paths(missing, deleted)
        message = unresolvable_advisory(missing)
        if message:
            findings.append(
                Finding(
                    RULE_UNRESOLVABLE,
                    ",".join(missing),
                    message,
                    ",".join(missing),
                )
            )

    if repo:
        branch, behind = repo_state(repo, env=env, run=run)
        staleness = advisory(repo, branch, behind)
        if staleness:
            findings.append(
                Finding(
                    RULE_STALE_CHECKOUT,
                    repo,
                    staleness,
                    f"branch={branch or ''} behind={behind}",
                )
            )

    if findings and state:
        mark_advised(key)
    return findings


def _event_env(event):
    if isinstance(event, dict) and isinstance(event.get("hook_freshness_env"), dict):
        return {str(key): str(value) for key, value in event["hook_freshness_env"].items()}
    return os.environ


def _event_settings_path(event):
    if isinstance(event, dict):
        path = event.get("hook_freshness_settings_path")
        if isinstance(path, str) and path:
            return path
    return SETTINGS_PATH


def _without_deleted_hook_paths(paths, deleted_hooks):
    if not deleted_hooks:
        return paths
    deleted = set(deleted_hooks)
    return [
        path for path in paths
        if os.path.basename(os.path.dirname(path)) not in deleted
    ]
