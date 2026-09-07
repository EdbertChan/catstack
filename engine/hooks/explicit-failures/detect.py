"""Find silent-failure shapes in the code an agent is about to write.

Advisory PreToolUse scanner for Edit, Write, MultiEdit, and Bash heredocs.
Off by default: enable with CATSTACK_EXPLICIT_FAILURES=1 or an
`.explicit-failures` marker file in the working directory or any parent
(CATSTACK_EXPLICIT_FAILURES=0 forces it off even with a marker).

Python shapes: an `except` handler whose body ends in `pass`, `continue`,
`break`, or a bare / None / empty return; an `if not x:` / `if x is None:`
guard whose last statement is such an exit. In both cases the block must
contain nothing that says the failure happened: no log, raise, warn, print,
status or reason assignment. JS/TS shapes: `catch {}` with an empty or
comment-only body (or a body that only continues / returns bare), a
`.catch(() => {})` no-op, and an `if (!x)` / `if (x == null)` guard whose
only statement is a bare exit. The substring `explicit-failures` on the
header line, the line before it, or inside the block suppresses a hit
(`# explicit-failures: allow`, `# pragma: explicit-failures: allow`,
`// eslint-disable-next-line explicit-failures`).
"""
from __future__ import annotations

import os
import re

ENABLED_ENV = "CATSTACK_EXPLICIT_FAILURES"
MARKER_NAME = ".explicit-failures"
PRINCIPLE = "explicit-failures: raise, log with context, or emit a status row (principle-explicit-errors)"
MAX_REPORTED = 12

PY_SUFFIXES = (".py", ".pyi")
JS_SUFFIXES = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte")

ALLOW_TOKEN_RE = re.compile(r"(?i)(?:\blog|_log\b|\braise\b|\bthrow\b|status|reason|warn|\bprint\s*\()")
ALLOW_MARK = "explicit-failures"

PY_EXCEPT_RE = re.compile(r"^(\s*)except\b[^:]*:\s*(\S.*)?$")
PY_GUARD_RE = re.compile(
    r"^(\s*)(?:if|elif)\s+(?:not\s+\S.*|.*\bis\s+None\b.*|.*==\s*None\b.*|len\(.*\)\s*==\s*0.*)\s*:\s*(\S.*)?$"
)
PY_BARE_EXIT_RE = re.compile(r"""^(?:continue|break|pass|return(?:\s+(?:None|\[\]|\{\}|\(\)|""|''))?)\s*(?:#.*)?$""")
PY_COMMENT_RE = re.compile(r"^\s*#")

JS_EXIT = r"(?:continue|break|return(?:\s+(?:null|undefined|\[\]|\{\}|\"\"|''))?)"
JS_CATCH_RE = re.compile(r"\bcatch\s*(?:\([^)]*\))?\s*\{")
JS_PROMISE_CATCH_RE = re.compile(
    r"\.catch\(\s*(?:(?:\([^)]*\)|\w+)\s*=>\s*(?:\{\s*\}|null|undefined|void\s+0)"
    r"|function\s*\w*\s*\([^)]*\)\s*\{\s*\}|noop)\s*\)"
)
JS_GUARD_RE = re.compile(
    r"\bif\s*\(\s*(?:!\s*[\w.$\[\]'\"]+|[\w.$\[\]'\"]+\s*===?\s*(?:null|undefined)"
    r"|(?:null|undefined)\s*===?\s*[\w.$\[\]]+|[\w.$\[\]]+\.length\s*===?\s*0)\s*\)\s*"
    r"(?:\{\s*" + JS_EXIT + r"\s*;?\s*\}|" + JS_EXIT + r"\s*;)"
)
JS_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
JS_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)

HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
REDIRECT_RE = re.compile(r">{1,2}\s*(['\"]?)([^\s'\"|;&<>]+)\1")


def enabled(cwd: str | None = None) -> bool:
    flag = os.environ.get(ENABLED_ENV, "").strip().lower()
    if flag in ("1", "true", "on", "yes"):
        return True
    if flag in ("0", "false", "off", "no"):
        return False
    here = os.path.abspath(cwd or os.getcwd())
    for _ in range(40):
        if os.path.exists(os.path.join(here, MARKER_NAME)):
            return True
        parent = os.path.dirname(here)
        if parent == here:
            return False
        here = parent
    return False


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _py_block(lines: list[str], start: int, header_indent: int) -> tuple[list[tuple[int, str]], int]:
    """Body lines (index, text) after the header at `start`; returns (body, next_index)."""
    body: list[tuple[int, str]] = []
    i = start + 1
    while i < len(lines):
        line = lines[i]
        if not line.strip() or PY_COMMENT_RE.match(line):
            body.append((i, line))
            i += 1
            continue
        if _indent(line) <= header_indent:
            break
        body.append((i, line))
        i += 1
    while body and (not body[-1][1].strip()):
        body.pop()
    return body, i


def _py_statement_lines(body: list[tuple[int, str]]) -> list[str]:
    real = [t for _, t in body if t.strip() and not PY_COMMENT_RE.match(t)]
    if not real:
        return []
    base = min(_indent(t) for t in real)
    return [t.strip() for t in real if _indent(t) == base]


def _allowed(header: str, prev: str, body_text: str) -> bool:
    if ALLOW_MARK in header or ALLOW_MARK in prev or ALLOW_MARK in body_text:
        return True
    return bool(ALLOW_TOKEN_RE.search(body_text))


def scan_python(text: str) -> list[tuple[int, str]]:
    """(1-based line, shape) for every silent-failure shape in Python source."""
    hits: list[tuple[int, str]] = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m_exc = PY_EXCEPT_RE.match(line)
        m_if = None if m_exc else PY_GUARD_RE.match(line)
        m = m_exc or m_if
        if not m:
            continue
        header_indent = len(m.group(1))
        inline = (m.group(2) or "").strip()
        prev = lines[i - 1] if i > 0 else ""
        if inline and not inline.startswith("#"):
            stmts = [inline]
            body_text = inline
        else:
            body, _ = _py_block(lines, i, header_indent)
            stmts = _py_statement_lines(body)
            body_text = "\n".join(t for _, t in body)
        if not stmts:
            continue
        last = stmts[-1]
        if not PY_BARE_EXIT_RE.match(last):
            continue
        if _allowed(line, prev, body_text):
            continue
        exit_word = last.split()[0]
        header = line.split("#")[0].strip()
        if m_exc:
            if exit_word == "pass":
                shape = f"`{header} pass`" if not inline else f"`{header}`"
            else:
                shape = f"`{header}` block that only {exit_word}s"
        else:
            if exit_word == "pass":
                continue
            shape = f"`{header}` guard that only {exit_word}s"
        hits.append((i + 1, shape))
    return hits


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _js_strip_comments(chunk: str) -> str:
    return JS_LINE_COMMENT_RE.sub("", JS_BLOCK_COMMENT_RE.sub("", chunk))


def _js_brace_body(text: str, open_pos: int) -> str | None:
    depth = 0
    for j in range(open_pos, len(text)):
        ch = text[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[open_pos + 1:j]
    return None


def _js_context(text: str, start: int, end: int) -> str:
    line_start = text.rfind("\n", 0, start) + 1
    prev_start = text.rfind("\n", 0, max(line_start - 1, 0)) + 1
    line_end = text.find("\n", end)
    return text[prev_start:len(text) if line_end < 0 else line_end]


def scan_js(text: str) -> list[tuple[int, str]]:
    """(1-based line, shape) for every silent-failure shape in JS/TS source."""
    hits: list[tuple[int, str]] = []
    for m in JS_CATCH_RE.finditer(text):
        body = _js_brace_body(text, m.end() - 1)
        if body is None:
            continue
        stripped = _js_strip_comments(body).strip().rstrip(";").strip()
        context = _js_context(text, m.start(), m.end()) + body
        if ALLOW_MARK in context:
            continue
        if stripped == "":
            hits.append((_line_of(text, m.start()), "`catch {}` with an empty body"))
        elif re.fullmatch(JS_EXIT, stripped) and not ALLOW_TOKEN_RE.search(body):
            hits.append((_line_of(text, m.start()), f"catch block that only `{stripped}`s"))
    for m in JS_PROMISE_CATCH_RE.finditer(text):
        if ALLOW_MARK in _js_context(text, m.start(), m.end()):
            continue
        hits.append((_line_of(text, m.start()), "`.catch(() => {})` no-op rejection handler"))
    for m in JS_GUARD_RE.finditer(text):
        if ALLOW_MARK in _js_context(text, m.start(), m.end()):
            continue
        head = m.group(0).split(")")[0] + ")"
        hits.append((_line_of(text, m.start()), f"`{head}` guard that only exits"))
    return sorted(set(hits))


def scan_text(path: str, text: str) -> list[tuple[int, str]]:
    if not text:
        return []
    ext = os.path.splitext(path.lower())[1] if path else ""
    if ext in PY_SUFFIXES:
        return scan_python(text)
    if ext in JS_SUFFIXES:
        return scan_js(text)
    if ext == "":
        return sorted(set(scan_python(text) + scan_js(text)))
    return []


def heredocs(command: str) -> list[tuple[str, str]]:
    """(target path or '', body) for every heredoc in a shell command."""
    out: list[tuple[str, str]] = []
    lines = command.splitlines()
    i = 0
    while i < len(lines):
        m = HEREDOC_RE.search(lines[i])
        if not m:
            i += 1
            continue
        delim = m.group(2)
        strip_tabs = "<<-" in lines[i]
        redirect = REDIRECT_RE.search(lines[i][m.end():]) or REDIRECT_RE.search(lines[i][:m.start()])
        path = redirect.group(2) if redirect else ""
        body: list[str] = []
        j = i + 1
        while j < len(lines):
            candidate = lines[j].lstrip("\t") if strip_tabs else lines[j]
            if candidate == delim:
                break
            body.append(lines[j])
            j += 1
        out.append((path, "\n".join(body)))
        i = j + 1
    return out


def added_text(tool_name: str, tool_input: dict) -> list[tuple[str, str]]:
    path = str(tool_input.get("file_path") or tool_input.get("path") or "")
    if tool_name == "Write":
        return [(path, str(tool_input.get("content") or ""))]
    if tool_name == "Edit":
        return [(path, str(tool_input.get("new_string") or ""))]
    if tool_name == "MultiEdit":
        return [(path, str(e.get("new_string") or "")) for e in (tool_input.get("edits") or []) if isinstance(e, dict)]
    if tool_name == "Bash":
        return heredocs(str(tool_input.get("command") or ""))
    return []


def report_lines(tool_name: str, tool_input: dict) -> list[str]:
    out: list[str] = []
    for path, text in added_text(tool_name, tool_input):
        label = path or "<heredoc>"
        for line_no, shape in scan_text(path, text):
            out.append(f"{label}:{line_no}: {shape} — {PRINCIPLE}")
    return out


def decide(payload: dict) -> str | None:
    """Advisory message for the agent, or None when nothing fires or the hook is off."""
    tool_name = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return None
    if not enabled(str(payload.get("cwd") or "") or None):
        return None
    lines = report_lines(tool_name, tool_input)
    if not lines:
        return None
    extra = len(lines) - MAX_REPORTED
    shown = lines[:MAX_REPORTED]
    if extra > 0:
        shown.append(f"(+{extra} more silent-failure shape(s) in this edit)")
    return "\n".join(shown)
