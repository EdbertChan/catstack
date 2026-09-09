"""ui-input-guard: never drive the user's own keyboard, mouse, or screen uninvited.

Synthetic input (AppleScript `System Events` keystrokes and clicks,
`cliclick`, `xdotool`) and screen recording act on the session the user is
sitting in. Typed into the wrong window they send real messages, trip real
shortcuts, and land in the lock screen; a recording captures whatever the
user has open.

A Bash command carrying one of those is blocked unless the user has granted
a hands-off window (a fresh marker file), the screen is unlocked, and the
user has been idle for a moment. Wrapper scripts count: a command that runs
a local file is scanned through that file's contents, because the tool text
alone hides what the script does.

Blunt on purpose. Probe errors fail open; a missing marker does not.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time

MARKER = os.environ.get("UI_INPUT_WINDOW_FILE", "/tmp/.ui-input-window")
MAX_WINDOW_AGE_SECS = 30 * 60
MIN_IDLE_SECS = 10
SCAN_CHUNK_BYTES = 64 * 1024
SCAN_OVERLAP_BYTES = 512
MAX_SCRIPT_BYTES = 8 * 1024 * 1024
PROBE_TIMEOUT_SECS = 3

SYNTHETIC_INPUT_RES = [
    (
        "AppleScript System Events input",
        re.compile(r"System\s+Events", re.IGNORECASE | re.DOTALL),
        re.compile(r"\bkeystroke\b|\bkey\s+code\b|\bclick\s+at\b", re.IGNORECASE | re.DOTALL),
    ),
]
COMMAND_MECHANISMS = [
    ("cliclick", "cliclick", None),
    ("xdotool", "xdotool", None),
    ("screencapture video", "screencapture", re.compile(r"\s-{1,2}[Vv]\b")),
    (
        "ffmpeg screen capture",
        "ffmpeg",
        re.compile(r"avfoundation[^\n]*Capture\s+screen", re.IGNORECASE),
    ),
]

READ_ONLY_COMMANDS = {
    "ack", "ag", "awk", "cat", "cd", "cut", "echo", "find", "fgrep", "git",
    "grep", "egrep", "head", "jq", "less", "ls", "printf", "pwd", "rg", "sed",
    "sort", "tail", "test", "tr", "type", "uniq", "wc", "which",
}
SHELL_INTERPRETERS = {"applescript", "bash", "expect", "osascript", "sh", "zsh"}
DATA_INTERPRETERS = {"node", "perl", "python", "python3", "ruby"}
INLINE_CODE_RE = re.compile(
    r"(?:^|[\s;|&(])(?:node|perl|python3?|ruby)\s+-\w*[ce]\w*\s+('(?:[^']|'\\'')*'|\"(?:[^\"\\]|\\.)*\")",
    re.DOTALL,
)
ENV_ASSIGN_RE = re.compile(r"^\w+=")

HEREDOC_RE = re.compile(r"^([^\n]*?)<<-?\s*['\"]?(\w+)['\"]?[^\n]*$", re.MULTILINE)
PATH_TOKEN_RE = re.compile(r"[\"']?((?:/|\./|\$\w+/|~/)[\w./$-]+\.(?:sh|bash|zsh|applescript|scpt|py|mjs|js))[\"']?")

UNSCANNABLE_PREFIX = "unscannable:"

UNSCANNABLE_MESSAGE = (
    "ui-input-guard: this command runs {path}, which could not be read to the "
    "end ({why}), so whether it drives the user's live session is unknown. A "
    "guard that cannot check does not assume safe. Either run the mechanism "
    "inline where it can be seen, split the script so the input-driving part "
    "is its own readable file, or grant a hands-off window with "
    "`touch {marker}` if you already know what it does."
)

MESSAGE = (
    "ui-input-guard: this command drives the user's live session ({reason}){where}. "
    "{state}\n"
    "Get an explicit hands-off window first, then `touch {marker}` (expires in 30 "
    "minutes). Prefer a surface that is not the user's own: a test channel or "
    "workspace, a throwaway profile, a second display, a VM, or a headless run. "
    "Never while the screen is locked or the user is typing."
)


def strip_write_heredocs(command):
    """Drop heredoc bodies that are data, keeping the ones an interpreter runs.

    `cat > script.sh <<'EOF'` authors text and `git commit -F -` carries a
    message; `osascript <<'AS'` runs what follows. Only a heredoc introduced
    by a shell or AppleScript interpreter is kept, so a Python or Node
    heredoc that merely holds these words as data does not fire.
    """
    text = command or ""
    for match in list(HEREDOC_RE.finditer(text)):
        introducer = match.group(1)
        tag = match.group(2)
        words = [w for w in introducer.split() if not ENV_ASSIGN_RE.match(w)]
        heads = {os.path.basename(w.strip("\"'()")) for w in words}
        if heads & SHELL_INTERPRETERS:
            continue
        body = re.compile(
            r"(" + re.escape(match.group(0)) + r")\n.*?\n" + re.escape(tag) + r"\s*$",
            re.DOTALL | re.MULTILINE,
        )
        text = body.sub(r"\1\n", text, count=1)
    return text


def split_segments(text):
    """Split a command into stages on unquoted `;`, `|`, `&&`, and newlines.

    Quote-aware: a `|` inside a search pattern is part of that pattern, not a
    pipe, so `git grep -E "a|b"` stays one read-only stage.
    """
    parts = []
    current = []
    quote = ""
    index = 0
    while index < len(text or ""):
        char = text[index]
        if char == "\\" and quote != "'":
            current.append(text[index:index + 2])
            index += 2
            continue
        if quote:
            if char == quote:
                quote = ""
            current.append(char)
        elif char in "'\"":
            quote = char
            current.append(char)
        elif char in ";\n|&":
            parts.append("".join(current))
            current = []
            while index + 1 < len(text) and text[index + 1] in "|&":
                index += 1
        else:
            current.append(char)
        index += 1
    parts.append("".join(current))
    return parts


def segments(command):
    """Pipeline stages, each with its leading command word resolved."""
    out = []
    for raw in split_segments(command or ""):
        segment = raw.strip()
        if not segment:
            continue
        words = [w for w in segment.split() if not ENV_ASSIGN_RE.match(w) and not w.startswith(("<", ">"))]
        head = os.path.basename(words[0].strip("\"'()")) if words else ""
        out.append((head, segment))
    return out


def is_read_only_pipeline(command):
    """True when every stage only reads: a search pattern is not an action."""
    stages = segments(command)
    if not stages:
        return False
    return all(head in READ_ONLY_COMMANDS for head, _ in stages if head)


def resolve_shell_vars(command):
    """Substitute `VAR=value` assignments made earlier in the same command.

    `S=/tmp/run; $S/drive.sh` is the shape an agent writes when it stages a
    helper script, so the path token has to be resolved before the file can
    be scanned at all.
    """
    text = command or ""
    for name, value in re.findall(r"(?m)(?:^|[;&|]\s*|^\s*)(\w+)=([^\s;&|]+)", text):
        if "$" in value:
            continue
        cleaned = value.strip("\"'")
        text = text.replace(f"${{{name}}}", cleaned).replace(f"${name}", cleaned)
    return text


def scan_file(path, opener=open, getsize=os.path.getsize):
    """(mechanism, unscannable reason) for one file, read in bounded chunks.

    Streams the whole file rather than skipping a large one: a silent skip is
    an unchecked file reported as clean. Past the hard ceiling, or on a read
    error, the reason is returned so the caller can refuse instead of
    guessing.
    """
    try:
        size = getsize(path)
    except OSError as exc:
        return None, f"stat failed: {exc.strerror or exc}"
    if size > MAX_SCRIPT_BYTES:
        return None, f"{size} bytes, over the {MAX_SCRIPT_BYTES}-byte scan ceiling"
    try:
        with opener(path, encoding="utf-8", errors="replace") as handle:
            carry = ""
            while True:
                chunk = handle.read(SCAN_CHUNK_BYTES)
                if not chunk:
                    return None, None
                reason = synthetic_input_reason(carry + chunk)
                if reason:
                    return reason, None
                carry = chunk[-SCAN_OVERLAP_BYTES:]
    except OSError as exc:
        return None, f"read failed: {exc.strerror or exc}"


def script_paths(command, isfile=os.path.isfile):
    """Local script paths this command runs, with shell variables resolved."""
    found = []
    for match in PATH_TOKEN_RE.finditer(resolve_shell_vars(command)):
        path = os.path.expanduser(match.group(1))
        if "$" in path or path in found:
            continue
        if isfile(path):
            found.append(path)
    return found


def strip_inline_program_text(command):
    """Drop code passed to a non-shell interpreter with -c or -e.

    `python3 -c "...keystroke..."` is a program that holds these words as
    data, the same as a Python heredoc; `osascript -e` is not stripped,
    because there the words are the mechanism.
    """
    text = command or ""
    for match in list(INLINE_CODE_RE.finditer(text)):
        text = text.replace(match.group(1), "''", 1)
    return text


def synthetic_input_reason(text):
    """Name of the synthetic-input mechanism in this text, or None."""
    haystack = text or ""
    for label, first_re, second_re in SYNTHETIC_INPUT_RES:
        if first_re.search(haystack) and second_re.search(haystack):
            return label
    for label, tool, flag_re in COMMAND_MECHANISMS:
        for head, segment in segments(haystack):
            if head != tool:
                continue
            if flag_re is None or flag_re.search(segment):
                return label
    return None


def find_reason(command, **io):
    """(reason, source) for a command, following wrapper scripts. ('', '') if clean.

    A third shape exists: `source` is the path of a script that could not be
    read to the end, returned with an empty reason so the caller refuses
    rather than treating an unchecked file as clean.
    """
    visible = strip_inline_program_text(strip_write_heredocs(command))
    if is_read_only_pipeline(visible):
        return "", ""
    reason = synthetic_input_reason(visible)
    if reason:
        return reason, "this command"
    unscannable = None
    for path in script_paths(visible, **{k: v for k, v in io.items() if k == "isfile"}):
        found, why = scan_file(path, **{k: v for k, v in io.items() if k in ("opener", "getsize")})
        if found:
            return found, "the script it runs"
        if why and unscannable is None:
            unscannable = (path, why)
    if unscannable:
        return "", UNSCANNABLE_PREFIX + "\t".join(unscannable)
    return "", ""


def _probe(args, run=None):
    runner = run or subprocess.run
    result = runner(args, capture_output=True, text=True, timeout=PROBE_TIMEOUT_SECS, check=False)
    return result.stdout or ""


def screen_is_locked(run=None):
    """True when the macOS login session is locked; None when unknown."""
    if sys.platform != "darwin":
        return None
    try:
        out = _probe(["ioreg", "-n", "Root", "-d1", "-a"], run=run)
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"CGSSessionScreenIsLocked</key>\s*<(true|false)/>", out)
    if not match:
        return False if "CGSSessionScreenIsLocked" not in out else None
    return match.group(1) == "true"


def idle_seconds(run=None):
    """Seconds since the last real keyboard or mouse event; None when unknown."""
    if sys.platform != "darwin":
        return None
    try:
        out = _probe(["ioreg", "-c", "IOHIDSystem"], run=run)
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', out)
    if not match:
        return None
    return int(match.group(1)) / 1_000_000_000


def window_age_seconds(marker=None, now=time.time, stat=os.stat):
    """Age of the hands-off marker in seconds, or None when there is none."""
    path = marker or MARKER
    try:
        return now() - stat(path).st_mtime
    except OSError:
        return None


def blocking_state(age, locked, idle, marker=None):
    """Why the live session is off limits right now, or '' when it is granted."""
    path = marker or MARKER
    if age is None:
        return f"No hands-off window is open ({path} is missing)."
    if age > MAX_WINDOW_AGE_SECS:
        return f"The hands-off window in {path} expired; ask for a new one."
    if locked is True:
        return "The screen is locked, so input would go to the lock screen."
    if idle is not None and idle < MIN_IDLE_SECS:
        return f"The user was active {idle:.0f}s ago; wait until the session is idle."
    return ""


def decide(payload, marker=None, now=time.time, stat=os.stat, run=None, **io):
    """Blocking feedback for a PreToolUse Bash call, or None to allow it."""
    tool_input = payload.get("tool_input") or {}
    command = tool_input.get("command") or ""
    reason, source = find_reason(command, **io)
    if not reason and source.startswith(UNSCANNABLE_PREFIX):
        path, why = source[len(UNSCANNABLE_PREFIX):].split("\t", 1)
        if blocking_state(
            window_age_seconds(marker=marker, now=now, stat=stat),
            screen_is_locked(run=run),
            idle_seconds(run=run),
            marker=marker,
        ):
            return UNSCANNABLE_MESSAGE.format(path=path, why=why, marker=marker or MARKER)
        return None
    if not reason:
        return None
    state = blocking_state(
        window_age_seconds(marker=marker, now=now, stat=stat),
        screen_is_locked(run=run),
        idle_seconds(run=run),
        marker=marker,
    )
    if not state:
        return None
    where = "" if source == "this command" else f" via {source}"
    return MESSAGE.format(reason=reason, where=where, state=state, marker=marker or MARKER)
