"""history-claim-check: a claim about repo history is one git command away.

Durations, counts, authorship and never/always statements about code are the
cheapest facts to check and the easiest to feel certain about without checking.
That combination is what ships them into a PR body, where they become durable
and are read as measured.

Fires only on commands that write a PR title or body to GitHub, and only where
that command is actually run, not where its words sit inside a string, a
comment or a heredoc. Everything else passes untouched.
"""
from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

# Fallback only: used when the line cannot be parsed, so publish words in it
# still count as publishing instead of the line passing as clean.
PUBLISH_RE = re.compile(
    r"\bgh\s+pr\s+(?:create|edit)\b|"
    r"\bgh\s+api\b[^|;\n]*\brepos/[^\s|;]+/pulls\b|"
    r"\bcreate-pr\.mjs\b",
)
PULLS_PATH = re.compile(r"(?:^|/)repos/\S+/pulls\b")
PUBLISH_SCRIPT = "create-pr.mjs"
INTERPRETERS = {"node", "bun", "deno", "tsx", "zx", "npx"}
SHELLS = {"bash", "sh", "zsh", "dash"}
KEYWORDS = {"!", "{", "}", "if", "then", "elif", "else", "do", "while", "until", "time"}
WRAPPERS = {"sudo", "env", "command", "exec", "nohup", "builtin", "nice", "timeout", "xargs"}
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\+?=")

BODY_FILE_FLAGS = ("--body-file", "-F", "--input")
SEPARATORS = ("&&", "||", ";;", "|&", ";", "&", "|", "(", ")")
WRITE_REDIRECTS = ("&>>", ">>", ">|", "&>", ">&", ">")
READ_REDIRECTS = ("<<<", "<>", "<&", "<")
OPERATORS = sorted(SEPARATORS + WRITE_REDIRECTS + READ_REDIRECTS + ("<<-", "<<"),
                   key=len, reverse=True)

CLAIMS = [
    (re.compile(r"\b(?:for|over|across|about|roughly|nearly|almost|~)?\s*"
                r"(?:\d+|a|one|two|three|four|five|six|seven|eight|nine|ten|twelve)"
                r"[-\s](?:month|year|week|day)s?\b", re.I),
     "duration", "git log -S '<string>' --format='%ad %h' --date=short"),
    (re.compile(r"\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+"
                r"(?:\w+\s+){0,2}"
                r"(?:reflect|review|pass|passes|session|sessions|commit|commits|PRs?|"
                r"attempt|attempts|instance|instances|file|files|time|times)\b"
                r"[^.\n]{0,80}?"
                r"\b(?:found|produced|said|flagged|fixed|landed|reported|caught|missed|"
                r"ever|never|loaded|ran)\b", re.I),
     "count", "count them: git log --grep=... | wc -l, or grep -c"),
    (re.compile(r"\b(?:written|authored|introduced|added|created)\s+by\b", re.I),
     "authorship", "git log --format='%an <%ae>' -- <path> | sort -u"),
    (re.compile(r"\b(?:never|always)\s+(?:\w+\s+){0,3}"
                r"(?:loaded|ran|run|fired|worked|existed|shipped|merged|landed|applied|called)\b",
                re.I),
     "never/always", "git log --all -S '<token>' -- <path>"),
    (re.compile(r"\b(?:first|last)\s+(?:introduced|added|appeared|broken|failing)\b", re.I),
     "first/last occurrence", "git log --all -S '<token>' --reverse --format='%ad %h'"),
]

EVIDENCE = re.compile(
    r"```|\bgit (?:log|blame|show|rev-list)\b|\b[0-9a-f]{7,40}\b|\bUNVERIFIED\b", re.I
)
WINDOW = 6

MESSAGE = (
    "history-claim-check: this PR body states {n} claim(s) about repo history with no "
    "adjacent evidence. Each is one git command:\n{detail}\n"
    "Run the command, paste its output beside the claim, or write UNVERIFIED: before it. "
    "A wrong duration or count in a PR body is read as measured and outlives the session."
)

ORDER_MESSAGE = (
    "history-claim-check: this same command writes {paths} and publishes it as the PR "
    "body. This check runs before the command does, so it can only read what the file "
    "holds right now (an older file, maybe another session's), not the text this command "
    "is about to write. Write the body file in one command, then publish it in a separate "
    "command, so the check reads what will actually be published."
)


class _Cmd:
    def __init__(self) -> None:
        self.words: list[str] = []
        self.writes: list[str] = []


def _commands(src: str) -> list[_Cmd]:
    """The simple commands a shell line runs, each with the files it redirects into.

    Just enough shell grammar to tell a run program from a quoted word: quotes,
    comments, operators, redirects, heredoc bodies (skipped, they never run),
    and $( ), <( ) and backticks (scanned, they do run). Raises ValueError on an
    unterminated quote or substitution, which the shell would refuse too.
    """
    out: list[_Cmd] = []
    _scan(src, 0, out, nested=False)
    return out


def _scan(s: str, i: int, out: list[_Cmd], nested: bool) -> int:
    cmd, word, started, target, heredocs, depth = _Cmd(), [], False, None, [], 0

    def flush_word() -> None:
        nonlocal word, started, target
        if started:
            text = "".join(word)
            if target is None:
                cmd.words.append(text)
            elif target == ">" or (target == ">&" and not re.fullmatch(r"\d*-?", text)):
                cmd.writes.append(text)
            elif target in ("<<", "<<-"):
                heredocs.append((text, target == "<<-"))
            target = None
        word, started = [], False

    def flush_cmd() -> None:
        nonlocal cmd, target
        flush_word()
        target = None
        if cmd.words or cmd.writes:
            out.append(cmd)
        cmd = _Cmd()

    n = len(s)
    while i < n:
        c = s[i]
        if c in " \t":
            flush_word()
            i += 1
        elif c == "\n":
            flush_cmd()
            i = _skip_heredocs(s, i + 1, heredocs)
            heredocs.clear()
        elif c == "\\":
            if s.startswith("\n", i + 1):
                i += 2
            else:
                word.append(s[i + 1:i + 2])
                started, i = True, i + 2
        elif c == "'":
            j = s.find("'", i + 1)
            if j < 0:
                raise ValueError("unterminated single quote")
            word.append(s[i + 1:j])
            started, i = True, j + 1
        elif c == '"':
            started, i = True, _double(s, i + 1, word, out)
        elif c == "`":
            started, i = True, _backtick(s, i + 1, word, out)
        elif s.startswith("$(", i) or (c in "<>" and s.startswith("(", i + 1) and not started):
            j = _scan(s, i + 2, out, nested=True)
            word.append(s[i:j])
            started, i = True, j
        elif c == "#" and not started:
            j = s.find("\n", i)
            i = n if j < 0 else j
        else:
            op = next((o for o in OPERATORS if s.startswith(o, i)), None)
            if op is None:
                word.append(c)
                started, i = True, i + 1
                continue
            i += len(op)
            if op in SEPARATORS:
                if op == ")" and nested and depth == 0:
                    flush_cmd()
                    return i
                depth += {"(": 1, ")": -1}.get(op, 0)
                depth = max(depth, 0)
                flush_cmd()
                continue
            if started and "".join(word).isdigit():
                word, started = [], False
            else:
                flush_word()
            target = op if op in (">&", "<<", "<<-") else ">" if op in WRITE_REDIRECTS else "<"
    if nested:
        raise ValueError("unterminated substitution")
    flush_cmd()
    return n


def _double(s: str, i: int, word: list[str], out: list[_Cmd]) -> int:
    while i < len(s):
        c = s[i]
        if c == '"':
            return i + 1
        if c == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt != "\n":
                word.append(nxt if nxt in '"\\$`' else c + nxt)
            i += 2
        elif s.startswith("$(", i):
            j = _scan(s, i + 2, out, nested=True)
            word.append(s[i:j])
            i = j
        elif c == "`":
            i = _backtick(s, i + 1, word, out)
        else:
            word.append(c)
            i += 1
    raise ValueError("unterminated double quote")


def _backtick(s: str, i: int, word: list[str], out: list[_Cmd]) -> int:
    j = i
    while j < len(s) and s[j] != "`":
        j += 2 if s[j] == "\\" else 1
    if j >= len(s):
        raise ValueError("unterminated backtick")
    _scan(s[i:j], 0, out, nested=False)
    word.append(s[i - 1:j + 1])
    return j + 1


def _skip_heredocs(s: str, i: int, heredocs: list[tuple[str, bool]]) -> int:
    """Step past the heredoc bodies that start at i: their text is input, not commands."""
    for delim, strip_tabs in heredocs:
        while i < len(s):
            j = s.find("\n", i)
            line = s[i:] if j < 0 else s[i:j]
            i = len(s) if j < 0 else j + 1
            if (line.lstrip("\t") if strip_tabs else line) == delim:
                break
    return i


def _all_commands(src: str) -> list[_Cmd]:
    """Every simple command the line runs, including the script of `bash -c '...'`."""
    cmds = _commands(src)
    for cmd in list(cmds):
        k = _program_index(cmd.words)
        if k is None or os.path.basename(cmd.words[k]) not in SHELLS:
            continue
        rest = cmd.words[k + 1:]
        for j, w in enumerate(rest[:-1]):
            if w.startswith("-") and not w.startswith("--") and "c" in w:
                cmds.extend(_all_commands(rest[j + 1]))
                break
    return cmds


def _program_index(words: list[str]) -> int | None:
    k = 0
    while k < len(words) and (words[k] in KEYWORDS or ASSIGNMENT.match(words[k])):
        k += 1
    return k if k < len(words) else None


def _publishes(words: list[str]) -> bool:
    k = _program_index(words)
    if k is None:
        return False
    starts = [k]
    if os.path.basename(words[k]) in WRAPPERS:
        # Where the wrapped program sits depends on the wrapper's own options.
        starts = range(k + 1, len(words))
    for p in starts:
        prog, rest = os.path.basename(words[p]), words[p + 1:]
        if prog == "gh" and rest[:1] == ["pr"] and rest[1:2] in (["create"], ["edit"]):
            return True
        if prog == "gh" and rest[:1] == ["api"] and any(PULLS_PATH.search(w) for w in rest[1:]):
            return True
        if prog == PUBLISH_SCRIPT or (
            prog in INTERPRETERS and any(os.path.basename(w) == PUBLISH_SCRIPT for w in rest)
        ):
            return True
    return False


def is_publication(text: str) -> bool:
    try:
        return any(_publishes(cmd.words) for cmd in _all_commands(text or ""))
    except ValueError:
        return bool(PUBLISH_RE.search(text or ""))


def _flag_values(tokens: list[str], flags: tuple[str, ...]) -> list[str]:
    values = []
    for i, tok in enumerate(tokens):
        name, eq, value = tok.partition("=")
        if eq and name.startswith("--") and name in flags:
            values.append(value)
        elif tok in flags and i + 1 < len(tokens):
            values.append(tokens[i + 1])
    return values


def _same_file(a: str, b: str, cwd: str | None) -> bool:
    # A `cd` between the write and the publish changes what a relative path means,
    # so a shared file name counts as the same file.
    def norm(p: str) -> str:
        return os.path.normpath(os.path.join(cwd or "", os.path.expanduser(p)))
    return norm(a) == norm(b) or os.path.basename(norm(a)) == os.path.basename(norm(b))


def same_line_writes(command: str, cwd: str | None = None) -> list[str]:
    """Body files this command publishes that the same command also writes.

    An unparseable line returns [] and keeps today's check; the shell would
    refuse to run it, so nothing gets published from it.
    """
    try:
        cmds = _all_commands(command or "")
    except ValueError:
        return []
    written = [w for cmd in cmds for w in cmd.writes]
    for cmd in cmds:
        k = _program_index(cmd.words)
        if k is not None and os.path.basename(cmd.words[k]) == "tee":
            written.extend(w for w in cmd.words[k + 1:] if not w.startswith("-"))
    bodies = [
        p for cmd in cmds if _publishes(cmd.words)
        for p in _flag_values(cmd.words, BODY_FILE_FLAGS) if p != "-"
    ]
    return [p for p in dict.fromkeys(bodies) if any(_same_file(p, w, cwd) for w in written)]


def body_text(command: str, cwd: str | None = None) -> str:
    """Everything the command would publish: inline bodies plus body/input files."""
    parts = []
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    parts.extend(_flag_values(tokens, ("--body", "-b", "--title", "-t")))
    for value in _flag_values(tokens, BODY_FILE_FLAGS):
        p = Path(value)
        if not p.is_absolute() and cwd:
            p = Path(cwd) / p
        try:
            parts.append(p.read_text(errors="replace"))
        except OSError:
            pass
    if "<<" in command:
        parts.append(command)
    return "\n".join(parts)


def unsourced_claims(text: str) -> list[str]:
    lines = (text or "").splitlines()
    found = []
    for n, line in enumerate(lines):
        for pattern, kind, how in CLAIMS:
            m = pattern.search(line)
            if not m:
                continue
            near = "\n".join(lines[max(0, n - WINDOW): n + WINDOW + 1])
            if EVIDENCE.search(near):
                continue
            found.append(f"  - {kind}: {m.group(0).strip()!r}\n    settle it: {how}")
    return found


def decide(command: str, cwd: str | None = None) -> str | None:
    if not is_publication(command):
        return None
    written = same_line_writes(command, cwd)
    if written:
        return ORDER_MESSAGE.format(paths=", ".join(written))
    problems = unsourced_claims(body_text(command, cwd))
    if not problems:
        return None
    return MESSAGE.format(n=len(problems), detail="\n".join(problems))
