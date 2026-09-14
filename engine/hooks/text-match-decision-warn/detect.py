"""Find newly added code that decides behaviour by matching human-readable text.

Regex here parses code syntax (identifiers, call shapes, literals); it never
judges what a prose string means. See README.md for the exact scope.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

HOOK = "text-match-decision-warn"
ALLOW_MARK = "text-match-decision-warn: allow"
MAX_CONTENT_BYTES = 1_000_000
MAX_BASELINE_BYTES = 2_000_000
MAX_REPORTED = 8
MAX_LINE_CHARS = 160

SCOPE_ERROR = "error-or-log-text"
SCOPE_OUTPUT = "tool-or-agent-output"
SCOPE_PROSE = "plan-or-task-prose"

SCOPE_WORDS = (
    (SCOPE_ERROR, frozenset({
        "error", "err", "exception", "exc", "stderr", "log", "traceback", "message", "msg", "failure", "reason",
    })),
    (SCOPE_OUTPUT, frozenset({
        "stdout", "output", "reply", "response", "comment", "transcript", "body", "completion", "answer",
    })),
    (SCOPE_PROSE, frozenset({"description", "prompt", "title", "summary", "instructions"})),
)
SHELL_OUTPUT_WORDS = frozenset({"out", "result"})
STRUCTURED_WORDS = frozenset({
    "code", "class", "type", "kind", "status", "id", "name", "key", "phase", "state", "path", "file", "url",
    "count", "len", "length", "level", "json", "field", "exit", "number",
})
STRINGY_WORDS = frozenset({"stderr", "stdout", "text", "output", "log", "traceback", "str", "line"})
PY_NOT_OPERANDS = frozenset({"not", "and", "or", "if", "else", "elif", "return", "in", "is", "lambda", "yield", "await"})

PY_SUFFIXES = (".py",)
JS_SUFFIXES = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts")
SH_SUFFIXES = (".sh", ".bash", ".zsh")

TEST_DIR_PARTS = frozenset({"tests", "test", "__tests__", "e2e", "spec", "fixtures", "testdata", "repro"})
TEST_FILE_RE = re.compile(
    r"(?:test_.*\.py|.*_test\.py|conftest\.py|.*\.(?:test|spec)\.[cm]?[jt]sx?"
    r"|(?:test|repro)[-_].*\.(?:sh|bash|zsh|[cm]?[jt]sx?)|.*[-_]test\.(?:sh|bash|zsh|[cm]?[jt]sx?))"
)
ASSERTION_LINE_RE = re.compile(r"^\s*(?:assert\b|assert\.\w+\(|expect\(|self\.assert\w*\(|t\.(?:true|false|is|regex)\()")

PATH_KEYS = ("file_path", "filePath", "path", "target_file", "targetFile")
WRITE_KEYS = ("content", "contents", "file_text", "code_edit", "codeEdit")
NEW_KEYS = ("new_string", "newString", "new_str")
OLD_KEYS = ("old_string", "oldString", "old_str")
PATCH_BEGIN = "*** Begin Patch"
PATCH_END = "*** End Patch"
PATCH_FILE_RE = re.compile(r"^\*\*\* (?:Add|Update) File: (.+)$")

WORD_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
KEY_LIKE_RE = re.compile(r"[A-Za-z_][\w-]*")
KEY_GET_RE = re.compile(r"\.get\(\s*([\"'])(?P<key>[A-Za-z_]\w*)\1\s*(?:,[^()]*)?\)")
KEY_INDEX_RE = re.compile(r"(?:\?\.)?\[\s*([\"'])(?P<key>[A-Za-z_]\w*)\1\s*\]")
JS_REGEX_LITERAL_RE = re.compile(r"(?<![\w)\]$/\\\"'`])/(?![/*\s])(?:\\.|\[(?:\\.|[^\]\\\n])*\]|[^/\\\n\[])+/[dgimsuy]*")
FOR_BEFORE_RE = re.compile(r"\bfor\s*$")
ANY_ALL_RE = re.compile(r"\b(?:any|all)\(")

EXPR = r"[A-Za-z_$][\w$]*(?:\??\.[A-Za-z_$][\w$]*)*"
NORMALIZERS = (
    r"(?:\??\.(?:lower|upper|strip|lstrip|rstrip|casefold|decode|trim|trimStart|trimEnd|"
    r"toLowerCase|toUpperCase|toString)\([^()]*\))*"
)
END = r"(?![\w$.(\[])"


def _subj(tag: str) -> str:
    return (
        rf"(?<![\w$.])(?:(?:str|String)\(\s*(?P<w_{tag}>{EXPR})\s*\)|(?P<b_{tag}>{EXPR}))"
        rf"(?P<n_{tag}>{NORMALIZERS})"
    )


def _shell_var(tag: str) -> str:
    return rf"\$\{{?(?P<v_{tag}>[A-Za-z_]\w*)\}}?"


PY_MEMBERSHIP = re.compile(
    rf"(?P<left>\"[KS]\"|'[KS]'|(?<![\w.])[A-Za-z_]\w*)\s+(?:not\s+)?in\s+{_subj('m')}{END}"
)
PY_PREFIX = re.compile(rf"{_subj('p')}\.(?:startswith|endswith)\(")
PY_REGEX = re.compile(
    rf"\bre\.(?:search|match|fullmatch|findall)\(\s*(?:[rRbB]?\"[KS]\"|[rRbB]?'[KS]'|[A-Za-z_][\w.]*)\s*,\s*{_subj('r')}{END}"
    rf"|\b(?!re\.)[A-Za-z_]\w*\.(?:search|match|fullmatch|findall)\(\s*{_subj('c')}{END}"
)
PY_DECISION = re.compile(r"^\s*(?:if|elif|while|return|and|or)\b|\b(?:any|all|bool|filter)\(|\bif\b.*\belse\b")

JS_SUBSTRING = re.compile(rf"{_subj('i')}\??\.(?:includes|startsWith|endsWith)\(")
JS_REGEX_TEST = re.compile(rf"(?:/R/[dgimsuy]*|\b[A-Za-z_$][\w$]*)\s*\.test\(\s*{_subj('t')}{END}")
JS_MATCH = re.compile(rf"{_subj('x')}\??\.(?:match|matchAll|search|indexOf)\(")
JS_DECISION = re.compile(
    r"^\s*(?:\}\s*)?(?:else\s+)?(?:if|while|return)\b|\?(?![.?])|&&|\|\||[!=]==?\s*-1|>=?\s*0|\bBoolean\(|!!"
)

SH_GREP_HERESTRING = re.compile(rf"\bgrep\b[^|;&]*<<<\s*\"?{_shell_var('h')}")
SH_ECHO_GREP = re.compile(rf"\b(?:echo|printf)\b[^|;&]*{_shell_var('e')}[^|;&]*\|\s*grep\b")
SH_GLOB_MATCH = re.compile(
    rf"\[\[\s*\"?{_shell_var('g')}\"?\s*(?:==?|!=)\s*\"?\*|\[\[\s*\"?{_shell_var('r')}\"?\s*=~"
)
SH_DECISION = re.compile(r"^\s*(?:if|elif|while|until)\b|&&|\|\|")

COMMENT_LINE = {
    "py": re.compile(r"^#"),
    "sh": re.compile(r"^#"),
    "js": re.compile(r"^(?://|/\*|\*)"),
}


@dataclass
class Hit:
    file_path: str
    line_no: int
    line: str
    rule: str
    scope: str
    baseline: str


@dataclass
class Scan:
    hits: list[Hit] = field(default_factory=list)
    unchecked: list[str] = field(default_factory=list)


def words(identifier: str) -> list[str]:
    return [w.lower() for w in WORD_RE.findall(identifier)]


def language(path: str) -> str | None:
    lowered = path.lower()
    if lowered.endswith(PY_SUFFIXES):
        return "py"
    if lowered.endswith(JS_SUFFIXES):
        return "js"
    if lowered.endswith(SH_SUFFIXES):
        return "sh"
    return None


def is_test_path(path: str) -> bool:
    parts = [p for p in re.split(r"[\\/]+", path) if p]
    if not parts:
        return False
    if any(part in TEST_DIR_PARTS for part in parts[:-1]):
        return True
    return bool(TEST_FILE_RE.fullmatch(parts[-1]))


def normalize(line: str, lang: str) -> str:
    text = KEY_GET_RE.sub(lambda m: "." + m.group("key"), line)
    text = KEY_INDEX_RE.sub(lambda m: "." + m.group("key"), text)
    if lang == "js":
        text = JS_REGEX_LITERAL_RE.sub("/R/", text)
    quotes = "'\"`" if lang == "js" else "'\""
    out: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if lang == "sh" and ch == '"':
            out.append(ch)
            i += 1
            continue
        if ch in quotes:
            j = i + 1
            buf: list[str] = []
            while j < len(text) and text[j] != ch:
                if text[j] == "\\" and j + 1 < len(text):
                    buf.append(text[j + 1])
                    j += 2
                    continue
                buf.append(text[j])
                j += 1
            content = "".join(buf)
            out.append(ch + ("K" if KEY_LIKE_RE.fullmatch(content) else "S") + ch)
            i = j + 1
            continue
        if ch == "#" and (lang == "py" or (lang == "sh" and (i == 0 or text[i - 1].isspace()))):
            break
        if lang == "js" and text.startswith("//", i):
            break
        out.append(ch)
        i += 1
    return "".join(out)


def _scope_of(identifier: str, *, shell: bool) -> str | None:
    last = re.split(r"\??\.", identifier)[-1]
    ws = set(words(last))
    if not ws or ws & STRUCTURED_WORDS:
        return None
    for scope, vocab in SCOPE_WORDS:
        if ws & vocab:
            return scope
    if shell and ws & SHELL_OUTPUT_WORDS:
        return SCOPE_OUTPUT
    return None


def _subject(match: re.Match, tag: str) -> tuple[str, bool] | None:
    wrapped = match.group(f"w_{tag}")
    expr = wrapped or match.group(f"b_{tag}")
    if not expr:
        return None
    scope = _scope_of(expr, shell=False)
    if scope is None:
        return None
    last_words = set(words(re.split(r"\??\.", expr)[-1]))
    stringy = bool(wrapped) or bool(match.group(f"n_{tag}")) or bool(last_words & STRINGY_WORDS)
    return scope, stringy


def _first_subject(pattern: re.Pattern, line: str, tags: tuple[str, ...]) -> str | None:
    for match in pattern.finditer(line):
        for tag in tags:
            if match.group(f"b_{tag}") is None and match.group(f"w_{tag}") is None:
                continue
            found = _subject(match, tag)
            if found:
                return found[0]
    return None


def _py_rules(line: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for match in PY_MEMBERSHIP.finditer(line):
        left = match.group("left")
        if left in PY_NOT_OPERANDS or FOR_BEFORE_RE.search(line[:match.start()]):
            continue
        subject = _subject(match, "m")
        if subject is None:
            continue
        scope, stringy = subject
        if left[1:2] == "S":
            allowed = True
        elif left[1:2] == "K":
            allowed = stringy
        else:
            allowed = stringy or bool(ANY_ALL_RE.search(line))
        if allowed:
            found.append(("py-membership", scope))
            break
    scope = _first_subject(PY_PREFIX, line, ("p",))
    if scope:
        found.append(("py-prefix", scope))
    if PY_DECISION.search(line):
        scope = _first_subject(PY_REGEX, line, ("r", "c"))
        if scope:
            found.append(("py-regex", scope))
    return found


def _js_rules(line: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    scope = _first_subject(JS_SUBSTRING, line, ("i",))
    if scope:
        found.append(("js-substring", scope))
    scope = _first_subject(JS_REGEX_TEST, line, ("t",))
    if scope:
        found.append(("js-regex-test", scope))
    if JS_DECISION.search(line):
        scope = _first_subject(JS_MATCH, line, ("x",))
        if scope:
            found.append(("js-match", scope))
    return found


def _shell_scope(pattern: re.Pattern, line: str, tags: tuple[str, ...]) -> str | None:
    for match in pattern.finditer(line):
        for tag in tags:
            name = match.group(f"v_{tag}")
            if name:
                scope = _scope_of(name, shell=True)
                if scope:
                    return scope
    return None


def _sh_rules(line: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if SH_DECISION.search(line):
        scope = _shell_scope(SH_GREP_HERESTRING, line, ("h",))
        if scope:
            found.append(("sh-grep-herestring", scope))
        scope = _shell_scope(SH_ECHO_GREP, line, ("e",))
        if scope:
            found.append(("sh-echo-grep", scope))
    scope = _shell_scope(SH_GLOB_MATCH, line, ("g", "r"))
    if scope:
        found.append(("sh-glob-match", scope))
    return found


RULES = {"py": _py_rules, "js": _js_rules, "sh": _sh_rules}


def scan_lines(path: str, added: list[tuple[int, str]], baseline: str) -> list[Hit]:
    lang = language(path)
    if lang is None or is_test_path(path):
        return []
    hits: list[Hit] = []
    for line_no, raw in added:
        stripped = raw.strip()
        if not stripped or ALLOW_MARK in raw or COMMENT_LINE[lang].match(stripped) or ASSERTION_LINE_RE.match(stripped):
            continue
        for rule, scope in RULES[lang](normalize(raw, lang)):
            hits.append(Hit(path, line_no, stripped[:MAX_LINE_CHARS], rule, scope, baseline))
    return hits


def read_baseline(path: str) -> tuple[str, set[str]]:
    """("absent" | "read" | "unreadable", stripped lines already on disk)."""
    try:
        size = os.path.getsize(path)
    except FileNotFoundError:
        return "absent", set()
    except OSError:
        return "unreadable", set()
    if size > MAX_BASELINE_BYTES:
        return "unreadable", set()
    try:
        with open(path, encoding="utf-8") as handle:
            return "read", {line.strip() for line in handle}
    except (OSError, UnicodeDecodeError):
        return "unreadable", set()


def _first_str(data: dict, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str):
            return value
    return None


def _strings(node: object, depth: int = 0):
    if depth > 4:
        return
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _strings(value, depth + 1)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value, depth + 1)


def _unescape(chunk: str) -> str:
    return chunk.replace("\\\\", "\x00").replace("\\n", "\n").replace('\\"', '"').replace("\\'", "'").replace("\x00", "\\")


def _patch_edits(tool_input: object) -> list[tuple[str, str, str]]:
    edits: list[tuple[str, str, str]] = []
    for value in _strings(tool_input):
        start = value.find(PATCH_BEGIN)
        if start < 0:
            continue
        end = value.find(PATCH_END, start)
        chunk = value[start:end + len(PATCH_END)] if end >= 0 else value[start:]
        if "\n" not in chunk and "\\n" in chunk:
            chunk = _unescape(chunk)
        sections: dict[str, tuple[list[str], list[str]]] = {}
        current: str | None = None
        for raw in chunk.splitlines():
            header = PATCH_FILE_RE.match(raw)
            if header:
                current = header.group(1).strip()
                sections.setdefault(current, ([], []))
                continue
            if raw.startswith("*** "):
                if not raw.startswith("*** Move to:"):
                    current = None
                continue
            if current is None:
                continue
            if raw.startswith("+"):
                sections[current][0].append(raw[1:])
            elif raw.startswith("-"):
                sections[current][1].append(raw[1:])
        for path, (added, removed) in sections.items():
            edits.append((path, "\n".join(added), "\n".join(removed)))
    return edits


def candidate_edits(tool_input: object) -> list[tuple[str, str, str | None]]:
    """(path, added text, replaced text or None for a whole-file write)."""
    if isinstance(tool_input, dict):
        path = _first_str(tool_input, PATH_KEYS) or ""
        written = _first_str(tool_input, WRITE_KEYS)
        if written is not None:
            return [(path, written, None)]
        new = _first_str(tool_input, NEW_KEYS)
        if new is not None:
            return [(path, new, _first_str(tool_input, OLD_KEYS) or "")]
        edits = tool_input.get("edits")
        if isinstance(edits, list):
            return [
                (path, _first_str(e, NEW_KEYS) or "", _first_str(e, OLD_KEYS) or "")
                for e in edits if isinstance(e, dict)
            ]
    return [(path, added, removed) for path, added, removed in _patch_edits(tool_input)]


def _tool_input(payload: dict) -> object:
    for key in ("tool_input", "toolInput", "arguments", "input"):
        if key in payload and payload[key] is not None:
            return payload[key]
    return {}


def _resolve(path: str, cwd: object) -> str:
    if os.path.isabs(path) or not isinstance(cwd, str) or not cwd:
        return path
    return os.path.join(cwd, path)


def evaluate(payload: dict) -> Scan:
    scan = Scan()
    for path, added_text, replaced in candidate_edits(_tool_input(payload)):
        if language(path) is None or is_test_path(path):
            continue
        size = len(added_text.encode("utf-8", errors="replace"))
        if size > MAX_CONTENT_BYTES:
            scan.unchecked.append(
                f"{path}: added content is {size} bytes, over the {MAX_CONTENT_BYTES}-byte scan cap; nothing in it was scanned"
            )
            continue
        if replaced is None:
            baseline, existing = read_baseline(_resolve(path, payload.get("cwd")))
        else:
            baseline, existing = "replaced-text", {line.strip() for line in replaced.splitlines()}
        added = [
            (i, line) for i, line in enumerate(added_text.splitlines(), 1)
            if line.strip() and line.strip() not in existing
        ]
        scan.hits.extend(scan_lines(path, added, baseline))
    return scan


GUIDANCE = (
    "Decide from recorded state or a structured field instead: a status or phase field, a launch-completed "
    "timestamp, a typed failure class, a gate state file, `--output json`, API fields, an exit code, or typed "
    "plan fields. Rule: cat-mode \"decide from recorded state, not text\" "
    "(corpus/skills/cat-mode/references/named-constraints.md). Advisory only; nothing was blocked. "
    f"If a line parses a fixed machine format on purpose, put `{ALLOW_MARK}` on that line."
)


def format_message(hits: list[Hit]) -> str:
    lines = [f"{HOOK}: new code decides behaviour by matching human-readable text."]
    for hit in hits[:MAX_REPORTED]:
        lines.append(f"- {hit.file_path or '<unknown file>'}:{hit.line_no} [{hit.rule}; {hit.scope}] `{hit.line}`")
    extra = len(hits) - MAX_REPORTED
    if extra > 0:
        lines.append(f"(+{extra} more in this edit)")
    lines.append(GUIDANCE)
    return "\n".join(lines)
