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
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_runner"))

from finding import Finding  # noqa: E402
from outcome import classify  # noqa: E402
from run import _metrics_path, _write_metrics  # noqa: E402

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

RULE_STALE_CHECKOUT = "hook-freshness.stale-checkout"
RULE_MODE_FLAG = "hook-freshness.mode-flag"
RULE_UNCHECKED_SETTINGS = "hook-freshness.unchecked-settings"
RULE_UNRESOLVABLE_SCRIPT = "hook-freshness.unresolvable-script"
RULE_DELETED_INSTALLED_HOOK = "hook-freshness.deleted-installed-hook"


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
    """(branch, commits behind trunk) for the checkout, or (None, None)."""
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


TRACKED_BASE_BRANCH = "main"
REINSTALL_TRIGGER_ROOTS = ("engine/hooks", "engine/skills", "corpus/skills", "product/skills")
REINSTALL_TIMEOUT_SECS = 300


def touches_reinstall_paths(paths):
    return any(
        path == root or path.startswith(root + "/")
        for path in paths
        for root in REINSTALL_TRIGGER_ROOTS
    )


def reinstall_target(repo, pinned, run=_run_git):
    """(head, reason). head is the sha to reinstall to when this checkout's
    HEAD moved forward on the tracked base branch onto hook or skill changes
    install.sh has not yet picked up; reason names why not otherwise."""
    if not repo or not pinned:
        return None, "no-baseline"
    branch = run(["branch", "--show-current"], repo)
    if branch != TRACKED_BASE_BRANCH:
        return None, "not-base-branch"
    head = run(["rev-parse", "HEAD"], repo)
    if not head:
        return None, "no-head"
    if head == pinned:
        return None, "up-to-date"
    diff_out = run(["diff", "--name-only", f"{pinned}..{head}"], repo)
    if diff_out is None:
        return None, "diff-unavailable"
    paths = [line for line in diff_out.splitlines() if line]
    if not touches_reinstall_paths(paths):
        return None, "no-reinstall-paths"
    return head, "trigger"


def _reinstall_lock_path(repo):
    digest = hashlib.sha256(repo.encode("utf-8")).hexdigest()[:16]
    return os.path.join(STATE_DIR, f"reinstall-{digest}.lock")


def _claim_reinstall_lock(repo):
    path = _reinstall_lock_path(repo)
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None
    except OSError as exc:
        sys.stderr.write(f"catstack-hook-error hook-freshness: could not claim reinstall lock {path}: {exc}\n")
        return None
    os.close(fd)
    return path


def _spawn_reinstall(repo, harness, session_id, lock_path):
    log_path = os.path.join(STATE_DIR, "reinstall.log")
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as errors:
        subprocess.Popen(
            [
                sys.executable or "python3",
                os.path.abspath(__file__),
                "reinstall",
                repo,
                harness or "",
                session_id or "",
                lock_path,
            ],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=errors,
        )


def trigger_auto_reinstall(repo, pinned, harness=None, session_id=None, run=_run_git, spawn=None):
    """Fires the background reinstall run when should_reinstall says to.
    Returns the reason a run did or did not start, never raises."""
    head, reason = reinstall_target(repo, pinned, run=run)
    if head is None:
        return reason
    lock_path = _claim_reinstall_lock(repo)
    if lock_path is None:
        return "locked"
    spawner = spawn or _spawn_reinstall
    try:
        spawner(repo, harness, session_id, lock_path)
    except OSError as exc:
        sys.stderr.write(f"catstack-hook-error hook-freshness: could not spawn auto-reinstall for {repo}: {exc}\n")
        try:
            os.unlink(lock_path)
        except OSError as unlink_exc:
            sys.stderr.write(
                f"catstack-hook-error hook-freshness: could not release reinstall lock {lock_path} "
                f"after a failed spawn: {unlink_exc}\n"
            )
        return "spawn-failed"
    return "triggered"


def run_reinstall(repo, harness, session_id, lock_path, run_subprocess=subprocess.run, timeout=REINSTALL_TIMEOUT_SECS):
    """Runs install.sh for `repo`, writes one runs.jsonl row through the
    shared hook-metrics writer, and releases the reinstall lock. Never
    raises -- a run.sh that cannot start is recorded as a crashed outcome,
    same as any other hook failure hook-health already watches for."""
    started = time.monotonic()
    timed_out = False
    install_sh = os.path.join(repo, "install.sh")
    try:
        proc = run_subprocess(["bash", install_sh], cwd=repo, capture_output=True, timeout=timeout)
        exit_code, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = 1
        stdout = exc.stdout or b""
        stderr = (exc.stderr or b"") + b"\ncatstack-hook-error hook-freshness: auto-reinstall timed out\n"
    except OSError as exc:
        exit_code = 1
        stdout = b""
        stderr = f"catstack-hook-error hook-freshness: could not run install.sh: {exc}\n".encode()
    outcome = classify(exit_code, stdout, stderr, timed_out)
    row = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "harness": harness or "claude",
        "hook": "hook-freshness",
        "script": "auto-reinstall",
        "event": "AutoReinstall",
        "session_id": session_id or None,
        "outcome": outcome,
        "exit_code": exit_code,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "rule_ids": [],
        "stdout_bytes": len(stdout),
        "stderr_tail": stderr.decode("utf-8", errors="replace")[-500:],
    }
    try:
        metrics_error = _write_metrics(row, _metrics_path())
        if metrics_error:
            sys.stderr.buffer.write(metrics_error)
    finally:
        try:
            os.unlink(lock_path)
        except OSError as exc:
            sys.stderr.write(
                f"catstack-hook-error hook-freshness: could not release reinstall lock {lock_path}: {exc}\n"
            )
    return row


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


def deleted_installed_hooks(repo, settings_path=SETTINGS_PATH, load=None, isdir=os.path.isdir):
    """Installed hook folder names absent from the checkout they point at."""
    if not repo:
        return [], None
    names, unreadable = installed_hook_folders(settings_path=settings_path, load=load)
    if unreadable:
        return [], unreadable
    missing = [
        name for name in names
        if not isdir(os.path.join(repo, "engine", "hooks", name))
    ]
    return missing, None


DELETED_INSTALLED_MESSAGE = (
    "hook-freshness: {count} installed hook folder(s) no longer exist in the "
    "catstack checkout behind ~/.claude/hooks: {names}. Those deleted hooks are "
    "still registered here, so this install can silently miss current gates. "
    "Run `git -C {repo} pull --ff-only`, `{repo}/install.sh`, and restart the harness."
)


def deleted_installed_advisory(names, repo):
    if not names:
        return None
    shown = ", ".join(names[:3])
    if len(names) > 3:
        shown += f", and {len(names) - 3} more"
    return DELETED_INSTALLED_MESSAGE.format(count=len(names), names=shown, repo=repo)


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
    repo = resolve_repo(env=env)
    if repo:
        pinned_for_reinstall = resolve_pinned_sha(env=env)
        if pinned_for_reinstall:
            trigger_auto_reinstall(
                repo,
                pinned_for_reinstall,
                harness=payload.get("_catstack_harness") or "claude",
                session_id=payload.get("session_id") or payload.get("conversation_id"),
                run=run,
            )
    key = payload.get("transcript_path") or payload.get("transcriptPath") or ""
    if state and already_advised(key):
        return []
    findings = []
    if mode_note:
        findings.append(_finding(RULE_MODE_FLAG, MODE_FLAG, mode_note, env.get(MODE_FLAG, "")))
    missing, unreadable = unresolvable_hooks(settings_path=settings_path, load=load, exists=exists)
    unresolvable = unresolvable_advisory(missing, unreadable)
    if unresolvable:
        rule_id = RULE_UNCHECKED_SETTINGS if unreadable else RULE_UNRESOLVABLE_SCRIPT
        subject = settings_path if unreadable else ", ".join(missing)
        evidence = unreadable if unreadable else subject
        findings.append(_finding(rule_id, subject, unresolvable, evidence))
    deleted, deleted_unreadable = deleted_installed_hooks(
        repo, settings_path=settings_path, load=load, isdir=isdir,
    )
    if deleted_unreadable and not unreadable:
        message = UNCHECKED_MESSAGE.format(reason=deleted_unreadable)
        findings.append(_finding(RULE_UNCHECKED_SETTINGS, settings_path, message, deleted_unreadable))
    deleted_note = deleted_installed_advisory(deleted, repo)
    if deleted_note:
        findings.append(_finding(RULE_DELETED_INSTALLED_HOOK, ", ".join(deleted), deleted_note, ", ".join(deleted)))
    if repo:
        pinned = resolve_pinned_sha(env=env)
        branch, behind = repo_state(repo, env=env, run=run, ref=pinned or "HEAD")
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


if __name__ == "__main__" and sys.argv[1:2] == ["reinstall"] and len(sys.argv) == 6:
    run_reinstall(sys.argv[2], sys.argv[3] or None, sys.argv[4] or None, sys.argv[5])
