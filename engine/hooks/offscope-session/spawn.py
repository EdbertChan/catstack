"""offscope-session: hand a drift hit to a fresh session somewhere else.

Naming the pivot is only half of it. The off-scope request still has to be
worked on, and the point of the finding is that it should not be worked on
*here*, where every later turn would re-send the finished work's context. So a
drift hit writes one handoff record -- the request verbatim, the repository, the
parent session, the harness, the judge's reason -- and, only when
`CATSTACK_OFFSCOPE_AUTOSPAWN` is `on` or `1`, opens a detached terminal running
a fresh session seeded from that record.

Three spawn outcomes, and none of them is silence:

- `offscope-session.spawn-started`     a terminal was opened.
- `offscope-session.spawn-disabled`    auto-spawn is off; the handoff is on
                                       disk and the one `! bash <path>` line
                                       starts it by hand.
- `offscope-session.spawn-unavailable` no terminal resolved, the harness
                                       command is missing, or the terminal
                                       exited non-zero. Same handback line.

`spawn-unavailable` is never reported as a detection failure: the judge decided
correctly, the machine simply could not open a window. The current session is
never blocked, never stopped, and never cleared -- the only effect here is a
file under the state directory plus the text of a finding.
"""
from __future__ import annotations

import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

try:
    from finding import Finding
except ImportError:
    from pathlib import Path

    SDK_DIR = Path(__file__).resolve().parents[1] / "_sdk"
    sys.path.insert(0, str(SDK_DIR))
    from finding import Finding

HOOK = "offscope-session"
STATE_ENV = "CATSTACK_OFFSCOPE_STATE_DIR"
AUTOSPAWN_ENV = "CATSTACK_OFFSCOPE_AUTOSPAWN"
TERMINAL_ENV = "CATSTACK_OFFSCOPE_TERMINAL"
AUTOSPAWN_ON = frozenset({"on", "1"})

SCHEMA = "catstack.offscope_handoff.v1"
REQUEST_KEY = "offscope_request"
RULE_DRIFT_HIT = "offscope-session.drift-hit"
RULE_SPAWN_STARTED = "offscope-session.spawn-started"
RULE_SPAWN_DISABLED = "offscope-session.spawn-disabled"
RULE_SPAWN_UNAVAILABLE = "offscope-session.spawn-unavailable"

HARNESS_COMMANDS = {"claude": "claude", "cursor": "cursor-agent", "codex": "codex"}
DEFAULT_HARNESS = "claude"
PROMPT_EVENT_HARNESS = {
    "UserPromptSubmit": "claude",
    "beforeSubmitPrompt": "cursor",
    "user_prompt_submit": "codex",
}

SPAWN_WAIT_SECONDS = 1.5
"""How long to watch the terminal before calling it started.

A terminal emulator hands the window to its own server and returns at once, so
exit 0 inside the window means started; `xterm` instead stays in the
foreground, so still-running at the deadline also means started. Only a
non-zero exit inside the window is a failure, which is the case this wait
exists to catch -- without it, a terminal that refuses to open would be
reported as a session that opened.
"""
REASON_CLIP = 300
REQUEST_CLIP = 8_000


def state_root() -> str:
    return os.environ.get(STATE_ENV) or os.path.join(
        os.path.expanduser("~"), ".cache", "catstack-offscope-session"
    )


def handoff_dir() -> str:
    return os.path.join(state_root(), "handoffs")


def script_dir() -> str:
    return os.path.join(state_root(), "scripts")


def log_path() -> str:
    return os.path.join(state_root(), "spawn.log")


def log(message: str) -> None:
    """Append one line to the state directory's own log.

    The spawned terminal's output goes here too. It must never go to this
    hook's standard error, which the harness parses as the hook's answer.
    """
    root = state_root()
    os.makedirs(root, exist_ok=True)
    with open(log_path(), "a", encoding="utf-8") as handle:
        handle.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {message}\n")


def problem(message: str, handoff_id: str, command: str) -> str:
    """The error line, kept in the log and handed back for the caller to print.

    Both surfaces, on purpose: stderr is what a person debugging the live
    session sees, the log is what survives the session. The caller does the
    printing so that every handler in this file shows its own stderr write --
    an error nobody can read is a swallowed error, and the CI gate
    `scripts/check_no_silent_hook_except.py` reads the handler body to prove it.
    """
    line = f"catstack-hook-error {HOOK}: {message} (handoff {handoff_id or 'none'}; command: {command or 'none'})"
    try:
        log(line)
    except OSError as exc:
        line = f"{line} -- and {log_path()} could not be written either: {exc}"
    return line


def write_json_atomic(path: str, data: dict) -> None:
    """Same shape as `llm-judge/judge.py`: temp file in the folder, then rename.

    A reader of the handoff folder never sees a half-written record, because
    `os.replace` is atomic within one filesystem and the temp file is created
    in the destination folder.
    """
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=folder, prefix=".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        os.replace(temp, path)
    except BaseException:
        os.unlink(temp)
        raise


def plain_id(handoff_id: object) -> str:
    """A handoff id that is a plain file name, or `ValueError`.

    The same refusal `judge.enqueue` makes about job ids: an id holding a slash
    or starting with a dot would write outside the handoff folder, or write a
    hidden file the folder listing skips.
    """
    text = str(handoff_id or "").strip() or uuid.uuid4().hex
    if os.path.basename(text) != text or text.startswith("."):
        raise ValueError(f"handoff id {text!r} is not a plain file name")
    return text


def harness_name(event: object) -> str:
    """Which harness the parent session is running under.

    An explicit `harness` field wins. Otherwise the prompt event's own name
    says it: only Claude Code sends `UserPromptSubmit`, only Cursor sends
    `beforeSubmitPrompt`, only Codex sends `user_prompt_submit`.
    """
    if not isinstance(event, dict):
        return DEFAULT_HARNESS
    named = event.get("harness")
    if isinstance(named, str) and named in HARNESS_COMMANDS:
        return named
    for key in ("hook_event_name", "hookEventName", "event"):
        value = event.get(key)
        if isinstance(value, str) and value in PROMPT_EVENT_HARNESS:
            return PROMPT_EVENT_HARNESS[value]
    return DEFAULT_HARNESS


def session_id(event: object) -> str:
    if not isinstance(event, dict):
        return ""
    for key in ("session_id", "sessionId", "conversation_id", "conversationId"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def event_cwd(event: object) -> str:
    if not isinstance(event, dict):
        return os.getcwd()
    cwd = event.get("cwd") or event.get("workspace_roots")
    if isinstance(cwd, list):
        cwd = cwd[0] if cwd else ""
    if isinstance(cwd, str) and cwd.strip():
        return cwd.strip()
    return os.getcwd()


def repo_root(start: str) -> str:
    """The nearest ancestor holding a `.git`, else `start` itself.

    The new session has to open in the repository the parent was working in, so
    that a relative path in the off-scope request still means the same file. A
    session outside any repository keeps its own directory.
    """
    current = os.path.abspath(start or os.getcwd())
    while True:
        if os.path.exists(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return os.path.abspath(start or os.getcwd())
        current = parent


def judge_reason(verdict: object) -> str:
    if not isinstance(verdict, dict):
        return ""
    answer = verdict.get("answer")
    if isinstance(answer, dict):
        why = answer.get("why")
        if isinstance(why, str) and why.strip():
            return why.strip()[:REASON_CLIP]
    reason = verdict.get("reason")
    return str(reason).strip()[:REASON_CLIP] if isinstance(reason, str) else ""


def offscope_request(verdict: object, request: object = None) -> str:
    for candidate in (request, verdict.get(REQUEST_KEY) if isinstance(verdict, dict) else None):
        if isinstance(candidate, str) and candidate.strip():
            return candidate[:REQUEST_CLIP]
    return ""


def handoff_record(verdict: object, event: object, request: object = None) -> dict:
    """Everything the new session needs, and nothing that goes stale.

    The request is carried verbatim rather than re-derived from the transcript,
    which by the time a verdict lands has already moved on.
    """
    return {
        "schema": SCHEMA,
        "id": plain_id(verdict.get("id") if isinstance(verdict, dict) else None),
        "hook": HOOK,
        "rule_id": RULE_DRIFT_HIT,
        "created_at": time.time(),
        "request": offscope_request(verdict, request),
        "repo_root": repo_root(event_cwd(event)),
        "parent_session_id": session_id(event),
        "harness": harness_name(event),
        "reason": judge_reason(verdict),
    }


def handoff_path(handoff_id: str) -> str:
    return os.path.join(handoff_dir(), f"{plain_id(handoff_id)}.json")


def script_path(handoff_id: str) -> str:
    return os.path.join(script_dir(), f"{plain_id(handoff_id)}.sh")


def write_handoff(record: dict) -> str:
    path = handoff_path(record["id"])
    write_json_atomic(path, record)
    return path


def script_text(record: dict) -> str:
    command = HARNESS_COMMANDS.get(record.get("harness"), HARNESS_COMMANDS[DEFAULT_HARNESS])
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            f"cd {shlex.quote(record['repo_root'])}",
            f"exec {command} {shlex.quote(record['request'])}",
            "",
        ]
    )


def write_script(record: dict) -> str:
    """The one file both routes run: the terminal, and the `! bash` handback.

    One file, not two: a pasted multi-line command loses its quoting in
    transit, and the request is arbitrary text a person typed. `! bash <path>`
    runs exactly the bytes written here.
    """
    path = script_path(record["id"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(script_text(record))
        os.chmod(temp, 0o755)
        os.replace(temp, path)
    except BaseException:
        os.unlink(temp)
        raise
    return path


def autospawn_on() -> bool:
    """Off unless asked for. A window opening unasked is worse than a sentence."""
    return os.environ.get(AUTOSPAWN_ENV, "").strip().lower() in AUTOSPAWN_ON


def headless() -> bool:
    return not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY")


def terminal_candidates(script: str, root: str) -> list[tuple[str, list[str]]]:
    """The ordered chain, most specific first.

    macOS opens the script with `open -a Terminal`, never `osascript`: `open`
    is handed a file path and re-parses nothing, while an AppleScript
    `do script` takes the command as a string that a second shell splits again
    -- so a request holding a quote, a dollar sign, or a newline would be
    re-interpreted on the way in. The request is arbitrary text a person typed,
    so the route that never re-quotes it is the only safe one.

    On Linux the explicit `CATSTACK_OFFSCOPE_TERMINAL` wins. tmux comes next,
    but only with no `DISPLAY` and no `WAYLAND_DISPLAY`: on a headless machine
    -- this repository's own automation, most of the time -- no window can open
    at all, so a detached tmux session is the whole point rather than a
    fallback. With a display present the ordinary emulators come first.
    """
    if platform.system() == "Darwin":
        return [("open -a Terminal", ["open", "-a", "Terminal", script])]
    candidates: list[tuple[str, list[str]]] = []
    override = os.environ.get(TERMINAL_ENV, "").strip()
    if override:
        parts = shlex.split(override)
        if parts:
            candidates.append((parts[0], parts + ["-e", "bash", script]))
    if headless():
        candidates.append(("tmux", ["tmux", "new-session", "-d", "-c", root, "bash", script]))
    candidates.extend(
        [
            ("x-terminal-emulator", ["x-terminal-emulator", "-e", "bash", script]),
            ("gnome-terminal", ["gnome-terminal", "--working-directory", root, "--", "bash", script]),
            ("konsole", ["konsole", "--workdir", root, "-e", "bash", script]),
            ("xterm", ["xterm", "-e", "bash", script]),
        ]
    )
    return candidates


def resolve_terminal(script: str, root: str) -> tuple[str, list[str]] | None:
    """The first candidate whose program is actually installed, or None."""
    for name, argv in terminal_candidates(script, root):
        found = shutil.which(argv[0])
        if found:
            return name, [found] + argv[1:]
    return None


def harness_command(harness: str) -> str | None:
    return shutil.which(HARNESS_COMMANDS.get(harness, HARNESS_COMMANDS[DEFAULT_HARNESS]))


def shown(argv: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in argv)


def start_terminal(argv: list[str], record: dict) -> str:
    """Start the terminal detached; return "" when it started, else the reason.

    Detached exactly as `judge.enqueue` does it -- `start_new_session=True`,
    `stdin` closed, output to a log file -- so the window outlives this hook
    process and cannot write into the stream the harness is reading.
    """
    root = state_root()
    os.makedirs(root, exist_ok=True)
    with open(log_path(), "a", encoding="utf-8") as handle:
        handle.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} handoff {record['id']}: {shown(argv)}\n")
        proc = subprocess.Popen(
            argv,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=handle,
            cwd=record["repo_root"],
        )
    try:
        code = proc.wait(timeout=SPAWN_WAIT_SECONDS)
    except subprocess.TimeoutExpired:
        return ""
    if code == 0:
        return ""
    return f"the terminal {shown(argv[:1])} exited {code}; see {log_path()}"


def handback(script: str) -> str:
    return f"! bash {script}"


def _started(record: dict, path: str, name: str) -> Finding:
    return Finding(
        rule_id=RULE_SPAWN_STARTED,
        subject=f"handoff:{record['id']}",
        message=(
            f"offscope-session: the off-scope request now has its own session, opened in {name} in "
            f"{record['repo_root']}. This session keeps the scope it already had. Handoff: {path}"
        ),
        evidence=record.get("reason") or "",
    )


def _disabled(record: dict, path: str, script: str) -> Finding:
    return Finding(
        rule_id=RULE_SPAWN_DISABLED,
        subject=f"handoff:{record['id']}",
        message=(
            f"offscope-session: auto-spawn is off ({AUTOSPAWN_ENV} is not on), so nothing was "
            f"started and this session was left alone. The off-scope request is saved at {path}. "
            f"Start it in its own session with:\n{handback(script)}"
        ),
        evidence=record.get("reason") or "",
    )


def _unavailable(record: dict, path: str, script: str, reason: str) -> Finding:
    tail = f" Start it yourself with:\n{handback(script)}" if script else ""
    return Finding(
        rule_id=RULE_SPAWN_UNAVAILABLE,
        subject=f"handoff:{record.get('id') or 'unknown'}",
        message=(
            f"offscope-session: the pivot was detected, but no new session could be opened: "
            f"{reason}. This is a spawn failure, not a detection failure. The off-scope request is "
            f"saved at {path or 'nowhere -- the handoff could not be written'}.{tail}"
        ),
        evidence=reason,
    )


def spawn(verdict: object, event: object = None, request: object = None) -> list[Finding]:
    """One drift hit in, exactly one spawn finding out.

    Fails open on every path: a state directory that cannot be written, a
    terminal that cannot be started, a request that never reached the verdict
    -- each is named on stderr and in the log, reported as
    `spawn-unavailable`, and costs nothing else. The live session is never
    blocked, stopped, or cleared.
    """
    record: dict = {}
    path = ""
    script = ""
    try:
        record = handoff_record(verdict, event, request)
        path = write_handoff(record)
        script = write_script(record)
    except Exception as exc:
        reason = f"the handoff could not be written: {type(exc).__name__}: {exc}"
        print(problem(reason, str(record.get("id") or ""), ""), file=sys.stderr)
        return [_unavailable(record, path, script, reason)]
    if not record["request"]:
        reason = f"the verdict carried no off-scope request under {REQUEST_KEY!r}"
        print(problem(reason, record["id"], ""), file=sys.stderr)
        return [_unavailable(record, path, script, reason)]
    if not autospawn_on():
        return [_disabled(record, path, script)]
    try:
        command = harness_command(record["harness"])
        if not command:
            reason = (
                f"the {record['harness']} command "
                f"{HARNESS_COMMANDS.get(record['harness'], '?')!r} is not installed"
            )
            print(problem(reason, record["id"], ""), file=sys.stderr)
            return [_unavailable(record, path, script, reason)]
        resolved = resolve_terminal(script, record["repo_root"])
        if resolved is None:
            reason = (
                "no terminal program is installed (tried "
                + ", ".join(name for name, _ in terminal_candidates(script, record["repo_root"]))
                + f"; set {TERMINAL_ENV} to name one)"
            )
            print(problem(reason, record["id"], ""), file=sys.stderr)
            return [_unavailable(record, path, script, reason)]
        name, argv = resolved
        failure = start_terminal(argv, record)
        if failure:
            print(problem(failure, record["id"], shown(argv)), file=sys.stderr)
            return [_unavailable(record, path, script, failure)]
        return [_started(record, path, name)]
    except Exception as exc:
        reason = f"starting the terminal failed: {type(exc).__name__}: {exc}"
        print(problem(reason, record.get("id", ""), ""), file=sys.stderr)
        return [_unavailable(record, path, script, reason)]
