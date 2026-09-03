"""Find comment lines the agent is about to add to a code file.

A comment is a line whose first non-blank text is #, //, /*, *, or <!--,
or a trailing # or // fragment after code. Machine directives are not
comments: shebangs, encoding lines, noqa, type:, pragma, pylint, mypy,
eslint, prettier, ts-ignore, ts-expect-error, istanbul, nosec, ruff,
fmt, and SPDX or license headers. Markdown, JSON, YAML, TOML and other
non-code files are out of scope. Docstrings are out of scope.
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
SLASH_LINE_RE = re.compile(r"^\s*(?://|/\*|\*(?!/)|<!--)")
STRING_RE = re.compile(r"""("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)""")
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


def comment_lines(path: str, text: str) -> list[str]:
    if not is_code_file(path) or not text:
        return []
    ext = os.path.splitext(path.lower())[1]
    hash_lang = ext in HASH_LANGS
    slash_lang = ext in SLASH_LANGS or ext in (".html", ".vue", ".svelte")
    hits: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or DIRECTIVE_RE.match(line):
            continue
        if hash_lang and HASH_LINE_RE.match(line):
            hits.append(line.strip())
            continue
        if slash_lang and SLASH_LINE_RE.match(line):
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
