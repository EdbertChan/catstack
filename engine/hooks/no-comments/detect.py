"""Find comment lines the agent is about to add to a code file.

A comment is a line whose first non-blank text is #, //, /*, *, or <!--,
or a trailing # or // fragment after code. Machine directives are not
comments: shebangs, encoding lines, noqa, type:, pragma, pylint, mypy,
eslint, prettier, ts-ignore, ts-expect-error, istanbul, nosec, ruff,
fmt, and SPDX or license headers. Markdown, JSON, YAML, TOML and other
non-code files are out of scope. Python triple-quoted strings are out
of scope: a docstring's usage examples and a markdown fixture's '#'
headings are string content, not comments.

A leading * counts only while a /* block comment is open. Outside one it
is code, such as the CSS universal selector or quoted text in HTML.
"""
from __future__ import annotations

import os
import re

CODE_SUFFIXES = (
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".sh", ".bash", ".zsh",
    ".go", ".rs", ".java", ".kt", ".swift", ".c", ".h", ".cc", ".cpp", ".hpp",
    ".m", ".mm", ".rb", ".php", ".cs", ".scala", ".css", ".scss", ".less",
    ".sql", ".lua", ".dart", ".vue", ".svelte", ".html",
)
HASH_LANGS = (".py", ".sh", ".bash", ".zsh", ".rb", ".pl")
SLASH_LANGS = (
    ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".rs", ".java", ".kt",
    ".swift", ".c", ".h", ".cc", ".cpp", ".hpp", ".m", ".mm", ".php", ".cs",
    ".scala", ".css", ".scss", ".less", ".sql", ".dart", ".vue", ".svelte",
)
DIRECTIVE_RE = re.compile(
    r"^\s*(?:#!|#\s*-\*-|#\s*(?:noqa|type:|pragma|pylint|mypy|ruff|fmt:|nosec|isort)"
    r"|//\s*(?:eslint|prettier|@ts-|tslint|istanbul|biome|@flow|#region|#endregion|swiftlint)"
    r"|/\*\s*(?:eslint|istanbul|global|jshint|@__PURE__)"
    r"|(?:#|//|/\*)\s*(?:SPDX|Copyright|Licensed|License))",
    re.IGNORECASE,
)
HASH_LINE_RE = re.compile(r"^\s*#")
SLASH_LINE_RE = re.compile(r"^\s*(?://|/\*|<!--)")
STAR_LINE_RE = re.compile(r"^\s*\*(?!/)")
BLOCK_TOKEN_RE = re.compile(r"/\*|\*/|//")
STRING_RE = re.compile(r"""("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)""")
TRIPLE_QUOTE_RE = re.compile(r'"""|\'\'\'')
TRAILING_HASH_RE = re.compile(r"\s#(?!\{)\s*\S")
TRAILING_SLASH_RE = re.compile(r"\s//\s*\S")
TRAILING_DIRECTIVE_RE = re.compile(
    r"\s(?:#|//)\s*(?:noqa|type:|pragma|pylint|mypy|ruff|fmt:|nosec|isort|nolint|"
    r"eslint|prettier|@ts-|tslint|istanbul|biome|swiftlint|NOSONAR)",
    re.IGNORECASE,
)


def is_code_file(path: str) -> bool:
    return path.lower().endswith(CODE_SUFFIXES)


def _strip_strings(line: str) -> str:
    return STRING_RE.sub('""', line)


def _starts_outside_triple_quotes(ext: str, lines: list[str]) -> list[bool]:
    """Per line, whether it begins outside every Python triple-quoted string.

    Only Python has triple-quoted strings among the hash languages, so every
    other extension is entirely outside by definition. Tracks parity across
    the text it is handed, which for the CI twin is the run of added diff
    lines rather than the whole file.
    """
    if ext != ".py":
        return [True] * len(lines)
    outside: list[bool] = []
    open_delim: str | None = None
    for line in lines:
        outside.append(open_delim is None)
        for match in TRIPLE_QUOTE_RE.finditer(line):
            token = match.group(0)
            if open_delim is None:
                open_delim = token
            elif open_delim == token:
                open_delim = None
    return outside


def _starts_inside_block_comment(lines: list[str]) -> list[bool]:
    """Per line, whether it begins inside an open /* block comment.

    Strings are blanked first and a // outside a block ends the scan of that
    line, so neither opens a block. An edit or diff run can start partway
    through a block comment; when the first delimiter in the text is a */
    with no opener before it, every line up to that closer counts as inside.
    """
    inside_at_start: list[bool] = []
    inside = False
    seen_delimiter = False
    for index, line in enumerate(lines):
        inside_at_start.append(inside)
        for match in BLOCK_TOKEN_RE.finditer(line if inside else _strip_strings(line)):
            token = match.group(0)
            if inside:
                if token == "*/":
                    inside = False
            elif token == "//":
                break
            elif token == "/*":
                inside = True
            elif not seen_delimiter:
                inside_at_start[: index + 1] = [True] * (index + 1)
            seen_delimiter = True
    return inside_at_start


def comment_lines(path: str, text: str) -> list[str]:
    if not is_code_file(path) or not text:
        return []
    ext = os.path.splitext(path.lower())[1]
    hash_lang = ext in HASH_LANGS
    slash_lang = ext in SLASH_LANGS or ext in (".html", ".vue", ".svelte")
    hits: list[str] = []
    raw_lines = text.splitlines()
    outside_triple_quotes = _starts_outside_triple_quotes(ext, raw_lines)
    inside_block = _starts_inside_block_comment(raw_lines) if slash_lang else [False] * len(raw_lines)
    for raw, outside, in_block in zip(raw_lines, outside_triple_quotes, inside_block):
        line = raw.rstrip()
        if not outside or not line.strip() or DIRECTIVE_RE.match(line):
            continue
        if hash_lang and HASH_LINE_RE.match(line):
            hits.append(line.strip())
            continue
        if slash_lang and (SLASH_LINE_RE.match(line) or (in_block and STAR_LINE_RE.match(line))):
            hits.append(line.strip())
            continue
        body = _strip_strings(line)
        if TRAILING_DIRECTIVE_RE.search(body):
            continue
        if hash_lang and TRAILING_HASH_RE.search(body):
            hits.append(line.strip())
        elif slash_lang and TRAILING_SLASH_RE.search(body):
            hits.append(line.strip())
    return hits


def added_text(tool_name: str, tool_input: dict) -> list[tuple[str, str]]:
    path = str(tool_input.get("file_path") or tool_input.get("path") or "")
    if tool_name == "Write":
        return [(path, str(tool_input.get("content") or ""))]
    if tool_name == "Edit":
        return [(path, str(tool_input.get("new_string") or ""))]
    if tool_name == "MultiEdit":
        return [(path, str(e.get("new_string") or "")) for e in (tool_input.get("edits") or []) if isinstance(e, dict)]
    return []


def decide(payload: dict) -> str | None:
    tool_name = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return None
    found: list[str] = []
    path = ""
    for path, text in added_text(tool_name, tool_input):
        found.extend(comment_lines(path, text))
    if not found:
        return None
    shown = "\n".join("  " + h[:100] for h in found[:5])
    return (
        f"no-comments: this edit adds {len(found)} comment line(s) to {path}. Comments are "
        "banned in code; the commit message and git blame carry the story. Machine "
        "directives (shebang, noqa, type:, eslint-disable, license) are allowed.\n" + shown
    )
