from __future__ import annotations

import functools
import importlib.util
import json
import os
import re
import stat
import sys
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.realpath(__file__))
MATCHER_PATH = os.path.join(os.path.dirname(HERE), "diu-stop", "claude_stop_check.py")
READ_CAP_BYTES = 1_000_000

DESTINATION_RE = re.compile(
    r"\bgh\s+(?:issue\s+(?:create|comment)|pr\s+comment|release\s+create|api)\b"
)
FENCE_RE = re.compile(r"```|~~~")
FILE_LINE_RE = re.compile(r"(?<![\w/.-])(?:[\w.-]+/)*[\w-]+\.[A-Za-z]\w*(?::\d+\b|#L\d+\b)")
PROMPT_LINE_RE = re.compile(r"^[ \t]*(?:\$|>>>)[ \t]+\S", re.M)
EXPANSION_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_{(0123456789@*#?$!-"
ASSIGNMENT_RE = re.compile(r"^[A-Za-z_]\w*=")
SHORT_FLAG_WITH_C_RE = re.compile(r"^-[A-Za-z]*c[A-Za-z]*$")

PREFIX_WORDS = {"command", "builtin", "exec", "nohup", "time", "sudo", "nice", "env",
                "{", "!", "if", "then", "elif", "else", "do", "while", "until"}
SHELLS = {"bash", "sh", "zsh", "dash"}
DESTINATIONS = {
    ("issue", "create"): (("--body", "-b", "--title", "-t"), ("--body-file", "-F")),
    ("issue", "comment"): (("--body", "-b"), ("--body-file", "-F")),
    ("pr", "comment"): (("--body", "-b"), ("--body-file", "-F")),
    ("release", "create"): (("--notes", "-n", "--title", "-t"), ("--notes-file", "-F")),
}
API_METHODS = {"POST", "PATCH"}
API_PROSE_KEYS = {"body", "title"}
STDIN_SOURCES = {
    "heredoc": "a heredoc",
    "here-string": "a here-string",
    "pipe": "a pipe",
    "redirect": "a `<` redirect",
    None: "stdin",
}


class ParseError(ValueError):
    pass


@dataclass
class Word:
    text: str = ""
    expand_at: int | None = None

    @property
    def expanded(self) -> bool:
        return self.expand_at is not None

    def tail(self, n: int) -> "Word":
        at = None if self.expand_at is None else max(0, self.expand_at - n)
        return Word(self.text[n:], at)


@dataclass
class Segment:
    words: list[Word] = field(default_factory=list)
    stdin: str | None = None
    outputs: list[Word] = field(default_factory=list)


@dataclass
class Finding:
    outcome: str
    destination: str
    detail: str
    claim: str = ""


class _Lexer:
    def __init__(self, text: str) -> None:
        self.s = text
        self.i = 0
        self.segments = [Segment()]
        self.word: Word | None = None
        self.redirect: str | None = None
        self.heredocs: list[tuple[str, bool]] = []

    def run(self) -> list[Segment]:
        s = self.s
        while self.i < len(s):
            c = s[self.i]
            nxt = s[self.i + 1:self.i + 2]
            if c == "\\":
                if nxt != "\n":
                    self._append(nxt)
                self.i += 2
            elif c in " \t":
                self._end_word()
                self.i += 1
            elif c == "\n":
                self._end_word()
                self._end_segment()
                self.i += 1
                self._skip_heredocs()
            elif c == "#" and self.word is None:
                j = s.find("\n", self.i)
                self.i = len(s) if j < 0 else j
            elif c == "'":
                j = s.find("'", self.i + 1)
                if j < 0:
                    raise ParseError("unterminated single quote")
                self._append(s[self.i + 1:j])
                self.i = j + 1
            elif c == '"':
                self._double_quoted()
            elif c == "`":
                j = s.find("`", self.i + 1)
                if j < 0:
                    raise ParseError("unterminated backtick")
                self._mark_expansion()
                self._append(s[self.i:j + 1])
                self.i = j + 1
            elif c == "$" and nxt and nxt in EXPANSION_CHARS:
                self._mark_expansion()
                self._append(c)
                self.i += 1
            elif c in "<>" or (c == "&" and nxt == ">"):
                self._redirect()
            elif c in ";&|()":
                self._operator()
            else:
                self._append(c)
                self.i += 1
        self._end_word()
        return [seg for seg in self.segments if seg.words or seg.outputs]

    def _append(self, text: str) -> None:
        if self.word is None:
            self.word = Word()
        self.word.text += text

    def _mark_expansion(self) -> None:
        if self.word is None:
            self.word = Word()
        if self.word.expand_at is None:
            self.word.expand_at = len(self.word.text)

    def _double_quoted(self) -> None:
        s = self.s
        j = self.i + 1
        self._append("")
        while True:
            if j >= len(s):
                raise ParseError("unterminated double quote")
            c = s[j]
            if c == '"':
                break
            if c == "\\" and s[j + 1:j + 2] in ('"', "\\", "$", "`", "\n"):
                if s[j + 1] != "\n":
                    self._append(s[j + 1])
                j += 2
                continue
            if c == "`" or (c == "$" and s[j + 1:j + 2] and s[j + 1] in EXPANSION_CHARS):
                self._mark_expansion()
            self._append(c)
            j += 1
        self.i = j + 1

    def _operator(self) -> None:
        self._end_word()
        two = self.s[self.i:self.i + 2]
        piped = two == "|&" or (two[:1] == "|" and two != "||")
        self.i += 2 if two in ("&&", "||", "|&", ";;") else 1
        self._end_segment("pipe" if piped else None)

    def _redirect(self) -> None:
        s = self.s
        if self.word is not None and self.word.text.isdigit() and not self.word.expanded:
            self.word = None
        else:
            self._end_word()
        if s.startswith("<<<", self.i):
            self.redirect, self.i = "here-string", self.i + 3
        elif s.startswith("<<-", self.i):
            self.redirect, self.i = "heredoc-strip", self.i + 3
        elif s.startswith("<<", self.i):
            self.redirect, self.i = "heredoc", self.i + 2
        elif s[self.i] == "<":
            self.redirect, self.i = "redirect", self.i + 1
        else:
            self.i += 1
            while self.i < len(s) and s[self.i] in ">|&":
                self.i += 1
            self.redirect = "out"

    def _end_word(self) -> None:
        word, self.word = self.word, None
        if word is None:
            return
        kind, self.redirect = self.redirect, None
        if kind is None:
            self.segments[-1].words.append(word)
        elif kind in ("heredoc", "heredoc-strip"):
            self.heredocs.append((word.text, kind == "heredoc-strip"))
            self.segments[-1].stdin = "heredoc"
        elif kind in ("here-string", "redirect"):
            self.segments[-1].stdin = kind
        elif kind == "out":
            self.segments[-1].outputs.append(word)

    def _end_segment(self, stdin: str | None = None) -> None:
        self.segments.append(Segment(stdin=stdin))

    def _skip_heredocs(self) -> None:
        s = self.s
        for delimiter, strip_tabs in self.heredocs:
            while self.i < len(s):
                j = s.find("\n", self.i)
                line = s[self.i:] if j < 0 else s[self.i:j]
                self.i = len(s) if j < 0 else j + 1
                if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                    break
        self.heredocs = []


def split_command(command: str) -> list[Segment]:
    return _Lexer(command).run()


@functools.cache
def _matcher():
    if (matcher_dir := os.path.dirname(MATCHER_PATH)) not in sys.path:
        sys.path.append(matcher_dir)
    spec = importlib.util.spec_from_file_location("diu_stop_claude_stop_check", MATCHER_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load the claim matcher from {MATCHER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.find_unverified_claim


def find_unverified_claim(text: str) -> str | None:
    return _matcher()(text)


def has_evidence(text: str) -> bool:
    return bool(FENCE_RE.search(text) or FILE_LINE_RE.search(text) or PROMPT_LINE_RE.search(text))


def _command_start(words: list[Word]) -> int:
    k = 0
    while k < len(words):
        word = words[k]
        if not word.expanded and ASSIGNMENT_RE.match(word.text):
            k += 1
        elif word.text in PREFIX_WORDS or word.text == "timeout":
            is_timeout = word.text == "timeout"
            k += 1
            while k < len(words) and words[k].text.startswith("-"):
                k += 1
            if is_timeout:
                k += 1
        else:
            break
    return k


def _resolve(path: str, cwd: str | None) -> str | None:
    path = os.path.expanduser(path)
    if os.path.isabs(path):
        return path
    return None if cwd is None else os.path.join(cwd, path)


def _note_write(written: set[str | None], target: Word, cwd: str | None) -> None:
    if target.text.isdigit() or target.text == "-" or target.text.startswith("/dev/"):
        return
    path = None if target.expanded else _resolve(target.text, cwd)
    written.add(None if path is None else os.path.normpath(path))


def _read_source(word: Word, cwd: str | None, seg: Segment, flag: str,
                 written: set[str | None]) -> tuple[str | None, str | None]:
    if word.expanded:
        return None, f"{flag} {word.text!r} uses shell expansion, so its value is not known before the command runs"
    if word.text == "-":
        return None, f"{flag} - reads the body from {STDIN_SOURCES.get(seg.stdin, 'stdin')}, which a PreToolUse hook cannot see"
    path = _resolve(word.text, cwd)
    if path is None:
        return None, f"{flag} {word.text!r} is relative to a directory the gate could not follow"
    if os.path.normpath(path) in written:
        return None, f"{flag} {word.text!r} is written earlier in this same command, so the file on disk is not what gh will send"
    if None in written:
        return None, f"{flag} {word.text!r} may be overwritten earlier in this same command by a write to a path the gate cannot resolve"
    try:
        info = os.stat(path)
        if not stat.S_ISREG(info.st_mode):
            return None, f"{flag} {word.text!r} is not a regular file"
        if info.st_size > READ_CAP_BYTES:
            return None, f"{flag} {word.text!r} is {info.st_size} bytes, over the {READ_CAP_BYTES}-byte read cap"
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read(), None
    except OSError as exc:
        return None, f"{flag} {word.text!r} cannot be read ({exc.strerror or exc})"


def _flag_values(words: list[Word], flags: tuple[str, ...]):
    k = 0
    while k < len(words):
        text = words[k].text
        for flag in flags:
            if text == flag and k + 1 < len(words):
                yield flag, words[k + 1]
                k += 1
                break
            if flag.startswith("--") and text.startswith(flag + "="):
                yield flag, words[k].tail(len(flag) + 1)
                break
            if not flag.startswith("--") and text.startswith(flag) and len(text) > 2 and not text.startswith("--"):
                yield flag, words[k].tail(2)
                break
        k += 1


def _judge(destination: str, pieces: list[str], problems: list[str]) -> list[Finding]:
    if problems:
        return [Finding("unchecked", destination, "; ".join(problems))]
    text = "\n\n".join(piece for piece in pieces if piece.strip())
    if not text or has_evidence(text):
        return []
    claim = find_unverified_claim(text)
    if claim is None:
        return []
    return [Finding("hit", destination, _paragraph_with(text, claim), claim)]


def _paragraph_with(text: str, claim: str) -> str:
    for para in re.split(r"\n\s*\n", text):
        if claim.lower() in para.lower():
            flat = " ".join(para.split())
            return flat if len(flat) <= 160 else flat[:157] + "..."
    return ""


def _check_subcommand(sub: tuple[str, ...], args: list[Word], seg: Segment, cwd: str | None,
                      written: set[str | None]) -> list[Finding]:
    inline_flags, file_flags = DESTINATIONS[sub]
    pieces: list[str] = []
    problems: list[str] = []
    for flag, word in _flag_values(args, inline_flags + file_flags):
        if flag in file_flags:
            text, problem = _read_source(word, cwd, seg, flag, written)
        elif word.expanded:
            text, problem = None, f"{flag} {word.text!r} uses shell expansion, so its value is not known before the command runs"
        else:
            text, problem = word.text, None
        if problem:
            problems.append(problem)
        else:
            pieces.append(text)
    return _judge("gh " + " ".join(sub), pieces, problems)


def _api_options(words: list[Word]) -> tuple[str | None, list[tuple[str, Word]], Word | None]:
    method = None
    fields: list[tuple[str, Word]] = []
    input_word = None
    k = 0
    while k < len(words):
        text = words[k].text
        nxt = words[k + 1] if k + 1 < len(words) else None
        if text in ("-X", "--method") and nxt is not None:
            method, k = nxt.text, k + 2
            continue
        if text.startswith("--method="):
            method = text.split("=", 1)[1]
        elif text.startswith("-X") and len(text) > 2:
            method = text[2:]
        elif text in ("-f", "--raw-field", "-F", "--field") and nxt is not None:
            fields.append((text, nxt))
            k += 2
            continue
        elif text.startswith(("--raw-field=", "--field=")):
            flag = text.split("=", 1)[0]
            fields.append((flag, words[k].tail(len(flag) + 1)))
        elif text[:2] in ("-f", "-F") and len(text) > 2 and not text.startswith("--"):
            fields.append((text[:2], words[k].tail(2)))
        elif text == "--input" and nxt is not None:
            input_word, k = nxt, k + 2
            continue
        elif text.startswith("--input="):
            input_word = words[k].tail(len("--input="))
        k += 1
    return method, fields, input_word


def _check_api(words: list[Word], seg: Segment, cwd: str | None, written: set[str | None]) -> list[Finding]:
    method, fields, input_word = _api_options(words)
    method = (method or ("POST" if fields or input_word is not None else "GET")).upper()
    if method not in API_METHODS:
        return []
    pieces: list[str] = []
    problems: list[str] = []
    carries_body = False
    for flag, word in fields:
        eq = word.text.find("=")
        if eq < 0:
            continue
        if word.expand_at is not None and word.expand_at < eq:
            problems.append(f"{flag} {word.text!r} has a field name that uses shell expansion")
            carries_body = True
            continue
        key, value = word.text[:eq], word.tail(eq + 1)
        if key not in API_PROSE_KEYS:
            continue
        carries_body = carries_body or key == "body"
        if flag in ("-F", "--field") and value.text.startswith("@"):
            text, problem = _read_source(value.tail(1), cwd, seg, f"{flag} {key}=@", written)
        elif value.expanded:
            text, problem = None, f"{flag} {word.text!r} uses shell expansion, so its value is not known before the command runs"
        else:
            text, problem = value.text, None
        if problem:
            problems.append(problem)
        else:
            pieces.append(text)
    if input_word is not None:
        text, problem = _read_source(input_word, cwd, seg, "--input", written)
        if problem:
            problems.append(problem)
            carries_body = True
        else:
            try:
                data = json.loads(text)
            except ValueError:
                data = None
            if isinstance(data, dict) and isinstance(data.get("body"), str):
                carries_body = True
                pieces.extend(data[key] for key in ("title", "body") if isinstance(data.get(key), str))
    if not carries_body:
        return []
    return _judge(f"gh api -X {method}", pieces, problems)


def _nested(script: Word, cwd: str | None, depth: int, via: str, written: set[str | None]) -> list[Finding]:
    if script.expanded:
        if DESTINATION_RE.search(script.text):
            return [Finding("unchecked", via, f"the {via} script uses shell expansion around a gh write")]
        return []
    return evaluate(script.text, cwd, depth + 1, written)


def evaluate(command: str, cwd: str | None = None, depth: int = 0,
             written: set[str | None] | None = None) -> list[Finding]:
    written = set() if written is None else written
    try:
        segments = split_command(command)
    except ParseError as exc:
        if DESTINATION_RE.search(command):
            return [Finding("unchecked", "gh", f"the command could not be parsed ({exc})")]
        return []
    findings: list[Finding] = []
    here = cwd
    for seg in segments:
        words = seg.words[_command_start(seg.words):]
        name = os.path.basename(words[0].text) if words and not words[0].expanded else None
        args = words[1:]
        if name != "gh":
            for target in seg.outputs + ([w for w in args if not w.text.startswith("-")] if name == "tee" else []):
                _note_write(written, target, here)
        if name is None:
            continue
        if name == "cd":
            here = None if args and args[0].expanded else _resolve(args[0].text if args else "~", here)
        elif name in SHELLS and depth < 3:
            for k, word in enumerate(args[:-1]):
                if SHORT_FLAG_WITH_C_RE.match(word.text):
                    findings += _nested(args[k + 1], here, depth, f"{name} -c", written)
                    break
        elif name == "eval" and depth < 3:
            joined = Word(" ".join(w.text for w in args), 0 if any(w.expanded for w in args) else None)
            findings += _nested(joined, here, depth, "eval", written)
        elif name == "gh" and args:
            sub = tuple(w.text for w in args[:2])
            if sub[:1] == ("api",):
                findings += _check_api(args[1:], seg, here, written)
            elif sub in DESTINATIONS:
                findings += _check_subcommand(sub, args[2:], seg, here, written)
    return findings


HIT_MESSAGE = (
    "external-claim-gate: `{destination}` would publish a cause or resolution claim "
    "with no evidence in the same body.\n"
    "  claim: \"{claim}\" in: \"{paragraph}\"\n"
    "  missing: the body has no fenced block, no file:line reference, no pasted command "
    "output (a `$ ` prompt line), and no `UNVERIFIED:` marker."
)
UNCHECKED_MESSAGE = (
    "external-claim-gate: UNCHECKED: the body of `{destination}` could not be read, so it "
    "has not been cleared: {detail}.\n"
    "  make it readable first: pass it inline with --body '...' (no $VAR, $(...) or "
    "backticks), or write it to a file in an earlier, separate command and pass its path."
)
EXITS = (
    "Two ways through:\n"
    "  1. Add the evidence to the body: the command you ran with its real output in a "
    "fenced block, or the file:line you read.\n"
    "  2. Prefix the claim with `UNVERIFIED:`."
)


def block_message(findings: list[Finding]) -> str:
    parts = []
    for finding in findings:
        if finding.outcome == "hit":
            parts.append(HIT_MESSAGE.format(
                destination=finding.destination, claim=finding.claim, paragraph=finding.detail))
        else:
            parts.append(UNCHECKED_MESSAGE.format(destination=finding.destination, detail=finding.detail))
    parts.append(EXITS)
    return "\n\n".join(parts)
