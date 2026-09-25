"""hook-freshness: the installed hooks are only as new as the pinned snapshot
install.sh last took of them.

`install.sh` symlinks `~/.claude/hooks/<name>` into a per-install snapshot of
`engine/hooks`, recording the source checkout and the commit it pinned in
`.catstack-source` next to the snapshot. A hook fix merged on `origin/main`
does nothing on this machine until that checkout is pulled forward and
install.sh reruns. This reads `.catstack-source` via the `diu-stop` symlink,
compares the pinned commit against `origin/main`, and returns one advisory
line for the turn.

Advisory only: no block, no LLM, no network unless
CATSTACK_HOOK_FRESHNESS=fetch. Fails open on every error.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import subprocess
import sys
import time

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


SOURCE_MARKER = ".catstack-source"


def _read_source_marker(realpath=os.path.realpath):
    """(repo, pinned_sha) install.sh's hook snapshot recorded, or (None, None)."""
    try:
        anchor_target = realpath(ANCHOR_LINK)
    except OSError:
        return None, None
    marker = os.path.join(os.path.dirname(anchor_target), SOURCE_MARKER)
    try:
        with open(marker, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return None, None
    repo = lines[0] if lines and lines[0] else None
    sha = lines[1] if len(lines) > 1 and lines[1] else None
    return repo, sha


def resolve_repo(env=None, realpath=os.path.realpath, isdir=os.path.isdir):
    """The catstack checkout the installed hooks were pinned from, or None."""
    env = env if env is not None else os.environ
    override = env.get("CATSTACK_HOOKS_REPO")
    if override:
        return override if isdir(os.path.join(override, ".git")) else None
    repo, _sha = _read_source_marker(realpath=realpath)
    return repo if repo and isdir(os.path.join(repo, ".git")) else None


def resolve_pinned_sha(env=None, realpath=os.path.realpath):
    """The commit install.sh pinned the installed hook snapshot to, or None."""
    env = env if env is not None else os.environ
    if env.get("CATSTACK_HOOKS_REPO"):
        return None
    _repo, sha = _read_source_marker(realpath=realpath)
    return sha


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


def repo_state(repo, env=None, run=_run_git, ref="HEAD"):
    """(branch, commits behind trunk) for ref (the pinned sha when known,
    else the checkout's own HEAD), or (None, None)."""
    env = env if env is not None else os.environ
    try:
        if freshness_mode(env)[0] == "fetch":
            run(["fetch", "--quiet", "origin", "main"], repo, FETCH_TIMEOUT_SECS)
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
        pinned = resolve_pinned_sha(env=env)
        branch, behind = repo_state(repo, env=env, run=run, ref=pinned or "HEAD")
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
