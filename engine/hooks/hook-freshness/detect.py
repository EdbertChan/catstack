"""hook-freshness: the installed hooks are only as new as the pinned snapshot
install.sh last took of them.

`install.sh` symlinks `~/.claude/hooks/<name>` into a per-install snapshot of
`engine/hooks`, recording the source checkout and the commit it pinned in
`.catstack-source` next to the snapshot. A hook fix merged on `origin/main`
does nothing on this machine until that checkout is pulled forward and
install.sh reruns. This reads `.catstack-source` via the `diu-stop` symlink,
compares the pinned commit against `origin/main`, and returns findings for the
shared hook runtime.

Being behind is advisory. Deleted installed hook folders are stop-mode in the
registry. No LLM, no network unless CATSTACK_HOOK_FRESHNESS=fetch. Fails open
on every error.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

from finding import Finding  # noqa: E402
from source_repo import SOURCE_MARKER, is_checkout, read_marker  # noqa: E402

STATE_DIR = os.environ.get(
    "HOOK_FRESHNESS_STATE_DIR",
    os.path.join(os.path.expanduser("~"), ".cache", "catstack-hook-freshness"),
)

ANCHOR_LINK = os.path.join(os.path.expanduser("~"), ".claude", "hooks", "diu-stop")
TRUNK = "origin/main"
BASE_BRANCH = "main"
FETCH_TIMEOUT_SECS = 3

_RUNNER_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_runner")
)
if _RUNNER_DIR not in sys.path:
    sys.path.insert(0, _RUNNER_DIR)
try:
    from outcome import classify as _classify_run
except ImportError:
    _classify_run = None

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

RULE_STALE_CHECKOUT = "hook-freshness.stale-checkout"
RULE_MODE_FLAG = "hook-freshness.mode-flag"
RULE_UNCHECKED_SETTINGS = "hook-freshness.unchecked-settings"
RULE_UNRESOLVABLE_SCRIPT = "hook-freshness.unresolvable-script"
RULE_DELETED_INSTALLED_HOOK = "hook-freshness.deleted-installed-hook"
RULE_UNCHECKED_SOURCE = "hook-freshness.unchecked-source"


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


LIVE_BRANCH = object()


class Source:
    """What the installed hooks were taken from, and why any part of it is unknown."""

    def __init__(self, repo=None, sha=None, branch=LIVE_BRANCH, hooks_dir=None, unchecked=None):
        self.repo = repo
        self.sha = sha
        self.branch = branch
        self.hooks_dir = hooks_dir
        self.unchecked = unchecked


def resolve_source(env=None, realpath=os.path.realpath, isdir=os.path.isdir):
    """Where the installed hooks came from. `unchecked` names what could not be read."""
    env = env if env is not None else os.environ
    override = env.get("CATSTACK_HOOKS_REPO")
    if override:
        if isdir(os.path.join(override, ".git")):
            return Source(repo=override, hooks_dir=os.path.join(override, "engine", "hooks"))
        return Source(unchecked=f"CATSTACK_HOOKS_REPO={override} is not a git checkout")
    try:
        anchor_target = realpath(ANCHOR_LINK)
    except OSError as exc:
        return Source(unchecked=f"{ANCHOR_LINK} could not be resolved ({type(exc).__name__}: {exc})")
    snapshot = os.path.dirname(anchor_target)
    marker = os.path.join(snapshot, SOURCE_MARKER)
    repo, sha, branch = read_marker(snapshot)
    if repo:
        if not isdir(os.path.join(repo, ".git")) and not is_checkout(repo):
            return Source(hooks_dir=snapshot, unchecked=f"{marker} names {repo}, which is not a git checkout")
        if not sha:
            return Source(
                repo=repo, branch=branch, hooks_dir=snapshot,
                unchecked=f"{marker} does not record the commit install.sh pinned",
            )
        return Source(repo=repo, sha=sha, branch=branch, hooks_dir=snapshot)
    legacy = os.path.dirname(os.path.dirname(snapshot))
    if isdir(os.path.join(legacy, ".git")):
        return Source(repo=legacy, hooks_dir=snapshot)
    return Source(unchecked=f"{marker} is missing or unreadable, so the install's source checkout is unknown")


def resolve_repo(env=None, realpath=os.path.realpath, isdir=os.path.isdir):
    """The catstack checkout the installed hooks were pinned from, or None."""
    return resolve_source(env=env, realpath=realpath, isdir=isdir).repo


def resolve_pinned_sha(env=None, realpath=os.path.realpath):
    """The commit install.sh pinned the installed hook snapshot to, or None."""
    return resolve_source(env=env, realpath=realpath).sha


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


def repo_state(repo, env=None, run=_run_git, ref="HEAD", branch=LIVE_BRANCH):
    """(branch, commits behind trunk), or (None, None).

    branch is the ref the install was taken from when known; LIVE_BRANCH reads
    the checkout's current branch, which is right only when the hooks follow it.
    """
    env = env if env is not None else os.environ
    try:
        if freshness_mode(env)[0] == "fetch":
            run(["fetch", "--quiet", "origin", "main"], repo, FETCH_TIMEOUT_SECS)
        if branch is LIVE_BRANCH:
            branch = run(["branch", "--show-current"], repo)
        behind_raw = run(["rev-list", "--count", f"{ref}..{TRUNK}"], repo)
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
    off_trunk = bool(branch) and branch != BASE_BRANCH
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

UNCHECKED_SOURCE_MESSAGE = (
    "hook-freshness: could not tell which catstack checkout and commit the installed hooks "
    "came from, because {reason}. Staleness is unchecked, not clean. Re-run your catstack "
    "`install.sh` to record it."
)

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


RUNNER_SUFFIX = "/_runner/run.py"


def _script_paths(command):
    expanded = os.path.expandvars(command).replace("~/", os.path.expanduser("~") + "/")
    tokens = [tok for tok in expanded.split() if "/" in tok and not tok.startswith("-")]
    runner = next((tok for tok in tokens if os.path.isabs(tok) and tok.endswith(RUNNER_SUFFIX)), None)
    if runner is None:
        return tokens
    hooks_root = os.path.dirname(os.path.dirname(runner))
    return [tok if os.path.isabs(tok) else os.path.join(hooks_root, tok) for tok in tokens]


def _hook_folder_from_path(path):
    pieces = path.replace("\\", "/").split("/")
    for idx in range(len(pieces) - 2, -1, -1):
        if pieces[idx] == "hooks" and idx + 1 < len(pieces):
            name = pieces[idx + 1]
            if name and not name.startswith("_"):
                return name
    return None


def installed_hook_folders(settings_path=SETTINGS_PATH, load=None):
    commands, unreadable = _hook_commands(settings_path, load=load)
    if unreadable:
        return [], unreadable
    names = []
    for command in commands:
        for path in _script_paths(command):
            name = _hook_folder_from_path(path)
            if name and name not in names:
                names.append(name)
    return names, None


def deleted_installed_hooks(hooks_dir, settings_path=SETTINGS_PATH, load=None, isdir=os.path.isdir):
    """Registered hook folder names absent from the hook tree the install runs from."""
    if not hooks_dir:
        return [], None
    names, unreadable = installed_hook_folders(settings_path=settings_path, load=load)
    if unreadable:
        return [], unreadable
    missing = [name for name in names if not isdir(os.path.join(hooks_dir, name))]
    return missing, None


DELETED_INSTALLED_MESSAGE = (
    "hook-freshness: {count} installed hook folder(s) no longer exist in {where}: "
    "{names}. Those deleted hooks are "
    "still registered here, so this install can silently miss current gates. "
    "Run `git -C {repo} pull --ff-only`, `{repo}/install.sh`, and restart the harness."
)


def deleted_installed_advisory(names, repo, where=None):
    if not names:
        return None
    shown = ", ".join(names[:3])
    if len(names) > 3:
        shown += f", and {len(names) - 3} more"
    return DELETED_INSTALLED_MESSAGE.format(
        count=len(names), names=shown, repo=repo or "<your catstack checkout>",
        where=where or "the hook tree behind ~/.claude/hooks",
    )


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


def _finding(rule_id, subject, message, evidence=""):
    return Finding(rule_id=rule_id, subject=subject, message=message, evidence=evidence)


def _findings(
    payload,
    env=None,
    run=_run_git,
    state=True,
    settings_path=SETTINGS_PATH,
    load=None,
    exists=os.path.exists,
    isdir=os.path.isdir,
):
    """Findings for this prompt. Once per session when state is enabled."""
    env = env if env is not None else os.environ
    mode, mode_note = freshness_mode(env)
    if mode == "off":
        return []
    key = payload.get("transcript_path") or payload.get("transcriptPath") or ""
    if state and already_advised(key):
        return []
    findings = []
    if mode_note:
        findings.append(_finding(RULE_MODE_FLAG, MODE_FLAG, mode_note, env.get(MODE_FLAG, "")))
    source = resolve_source(env=env, isdir=isdir)
    repo = source.repo
    if source.unchecked:
        message = UNCHECKED_SOURCE_MESSAGE.format(reason=source.unchecked)
        findings.append(_finding(RULE_UNCHECKED_SOURCE, SOURCE_MARKER, message, source.unchecked))
    missing, unreadable = unresolvable_hooks(settings_path=settings_path, load=load, exists=exists)
    unresolvable = unresolvable_advisory(missing, unreadable)
    if unresolvable:
        rule_id = RULE_UNCHECKED_SETTINGS if unreadable else RULE_UNRESOLVABLE_SCRIPT
        subject = settings_path if unreadable else ", ".join(missing)
        evidence = unreadable if unreadable else subject
        findings.append(_finding(rule_id, subject, unresolvable, evidence))
    deleted, deleted_unreadable = deleted_installed_hooks(
        source.hooks_dir, settings_path=settings_path, load=load, isdir=isdir,
    )
    if deleted_unreadable and not unreadable:
        message = UNCHECKED_MESSAGE.format(reason=deleted_unreadable)
        findings.append(_finding(RULE_UNCHECKED_SETTINGS, settings_path, message, deleted_unreadable))
    deleted_note = deleted_installed_advisory(deleted, repo, where=source.hooks_dir)
    if deleted_note:
        findings.append(_finding(RULE_DELETED_INSTALLED_HOOK, ", ".join(deleted), deleted_note, ", ".join(deleted)))
    if repo and not source.unchecked:
        branch, behind = repo_state(repo, env=env, run=run, ref=source.sha or "HEAD", branch=source.branch)
        staleness = advisory(repo, branch, behind)
        if staleness:
            evidence = f"branch={branch or ''}; behind={behind}"
            findings.append(_finding(RULE_STALE_CHECKOUT, repo, staleness, evidence))
    if not findings:
        return []
    if state:
        mark_advised(key)
    return findings


def detect(event):
    if event.get("_payload_error"):
        return []
    settings_path = event.get("settings_path")
    if not isinstance(settings_path, str) or not settings_path:
        settings_path = SETTINGS_PATH
    return _findings(event, settings_path=settings_path)


def decide(
    payload,
    env=None,
    run=_run_git,
    state=True,
    settings_path=SETTINGS_PATH,
    load=None,
    exists=os.path.exists,
    isdir=os.path.isdir,
):
    """Advisory context for this prompt, or None. Once per session."""
    findings = _findings(
        payload,
        env=env,
        run=run,
        state=state,
        settings_path=settings_path,
        load=load,
        exists=exists,
        isdir=isdir,
    )
    if not findings:
        return None
    line = "\n".join(finding.message for finding in findings)
    return line


def decide_json(
    payload,
    env=None,
    run=_run_git,
    state=True,
    settings_path=SETTINGS_PATH,
    load=None,
    exists=os.path.exists,
    isdir=os.path.isdir,
):
    line = decide(
        payload,
        env=env,
        run=run,
        state=state,
        settings_path=settings_path,
        load=load,
        exists=exists,
        isdir=isdir,
    )
    if not line:
        return None
    return json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": line,
        }
    })


REINSTALL_TRIGGER_PREFIXES = (
    "engine/hooks/",
    "engine/skills/",
    "corpus/skills/",
    "product/skills/",
)
REINSTALL_LOCK_STALE_SECONDS = 300
REINSTALL_HOOK_NAME = "hook-freshness"
REINSTALL_SCRIPT_NAME = "install.sh"


def repo_head(repo, run=_run_git):
    """The repo's own live HEAD sha, or None."""
    return run(["rev-parse", "HEAD"], repo)


def changed_paths(repo, old_sha, new_sha, run=_run_git):
    """Paths that differ between old_sha and new_sha, or [] when either sha
    is missing, they are equal, or git could not compute the diff."""
    if not old_sha or not new_sha or old_sha == new_sha:
        return []
    out = run(["diff", "--name-only", f"{old_sha}..{new_sha}"], repo)
    if out is None:
        return []
    return [line for line in out.splitlines() if line]


def touches_reinstall_dirs(paths):
    return any(path.startswith(REINSTALL_TRIGGER_PREFIXES) for path in paths)


def should_auto_reinstall(branch, pinned_sha, head_sha, paths):
    """True only on the tracked base branch, with a real move since the last
    pinned install, whose diff touches a hook or skill directory."""
    if branch != BASE_BRANCH:
        return False
    if not pinned_sha or not head_sha or pinned_sha == head_sha:
        return False
    return touches_reinstall_dirs(paths)


def _reinstall_lock_path():
    return os.path.join(STATE_DIR, "reinstall.lock")


def claim_reinstall_lock(path, stale_seconds=REINSTALL_LOCK_STALE_SECONDS):
    """True once this process owns the lock. A lock older than stale_seconds
    is treated as left behind by a crashed run and reclaimed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            age = time.time() - os.stat(path).st_mtime
        except FileNotFoundError:
            return claim_reinstall_lock(path, stale_seconds)
        if age < stale_seconds:
            return False
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        return claim_reinstall_lock(path, stale_seconds)
    os.close(fd)
    return True


def release_reinstall_lock(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def _metrics_path():
    root = os.environ.get("CATSTACK_HOOK_METRICS_DIR")
    if not root:
        root = os.path.expanduser(os.path.join("~", ".cache", "catstack-hook-metrics"))
    return os.path.join(root, "runs.jsonl")


def _reinstall_row(exit_code, duration_ms, stdout, stderr, timed_out=False):
    outcome = (
        _classify_run(exit_code, stdout, stderr, timed_out)
        if _classify_run is not None
        else ("crashed" if exit_code else "spoke")
    )
    return {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "harness": "claude",
        "hook": REINSTALL_HOOK_NAME,
        "script": REINSTALL_SCRIPT_NAME,
        "event": "UserPromptSubmit",
        "session_id": None,
        "outcome": outcome,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "rule_ids": [],
        "stdout_bytes": len(stdout),
        "stderr_tail": stderr.decode("utf-8", errors="replace")[-500:],
    }


def _write_reinstall_row(row, metrics_path=None):
    path = metrics_path or _metrics_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    except OSError as exc:
        print(
            f"catstack-hook-error hook-freshness: could not write reinstall row to {path}: {exc}",
            file=sys.stderr,
        )


def run_reinstall(repo, lock_path, metrics_path=None, popen=subprocess.Popen):
    """Runs repo/install.sh to completion, logs one runs.jsonl row, releases
    the lock. Meant to run detached from the prompt hook that spawned it."""
    try:
        install_script = os.path.join(repo, REINSTALL_SCRIPT_NAME)
        started = time.monotonic()
        proc = popen(
            ["bash", install_script, "--auto"],
            cwd=repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = proc.communicate()
        duration_ms = int((time.monotonic() - started) * 1000)
        row = _reinstall_row(proc.returncode, duration_ms, stdout, stderr)
        _write_reinstall_row(row, metrics_path=metrics_path)
    finally:
        release_reinstall_lock(lock_path)


def spawn_reinstall(repo, popen=subprocess.Popen, python=None, lock_path=None):
    """Claims the reinstall lock and starts a detached worker that runs
    run_reinstall. Returns False without doing anything when the lock is
    already held (another trigger is in flight)."""
    lock = lock_path or _reinstall_lock_path()
    if not claim_reinstall_lock(lock):
        return False
    try:
        popen(
            [python or sys.executable or "python3", os.path.abspath(__file__), "reinstall", repo, lock],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        release_reinstall_lock(lock)
        print(f"catstack-hook-error hook-freshness: could not spawn reinstall: {exc}", file=sys.stderr)
        return False
    return True


def maybe_reinstall(payload, env=None, run=_run_git, spawn=spawn_reinstall, exists=os.path.isfile):
    """Auto-reinstalls when the pinned repo sits on the tracked base branch
    and has moved past a hook or skill change since the last install."""
    env = env if env is not None else os.environ
    if freshness_mode(env)[0] == "off":
        return False
    repo = resolve_repo(env=env)
    if not repo:
        return False
    pinned = resolve_pinned_sha(env=env)
    head = repo_head(repo, run=run)
    branch = run(["branch", "--show-current"], repo)
    paths = changed_paths(repo, pinned, head, run=run)
    if not should_auto_reinstall(branch, pinned, head, paths):
        return False
    if not exists(os.path.join(repo, REINSTALL_SCRIPT_NAME)):
        return False
    return spawn(repo)


if __name__ == "__main__" and sys.argv[1:2] == ["reinstall"] and len(sys.argv) == 4:
    run_reinstall(sys.argv[2], sys.argv[3])
