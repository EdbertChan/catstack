"""Boundary parser: turn a shell tool call into the commands it will run.

The hook decides on `Command` values, never on the raw payload text, so a
string that only mentions a command (a quoted argument, a grep pattern, a
heredoc body) is one word inside another command, not a command of its own.
Tokenizing uses the standard library's POSIX shell lexer; the only shell
syntax handled beyond it is what changes which words form a command:
command separators, line continuations, heredoc bodies, leading variable
assignments, and `cd` changing the directory later commands run in.

A script the lexer cannot read (an unbalanced quote) parses to None, and the
caller reports it as unparseable rather than as "no command found".
"""
from __future__ import annotations

import json
import os
import shlex
from dataclasses import dataclass
from string import Template

SEPARATORS = frozenset({";", "&&", "||", "|", "&", "|&", "(", ")", ";;"})
HEREDOC_OPERATORS = frozenset({"<<", "<<-"})


@dataclass(frozen=True)
class Command:
    argv: tuple[str, ...]
    cwd: str
    variables: tuple[tuple[str, str], ...] = ()

    def expand(self, word: str) -> str | None:
        """Expand `$NAME`/`${NAME}` from earlier assignments in the script, then the environment.

        None when a reference stays unresolved, so the caller reports it instead of guessing.
        """
        mapping = dict(os.environ)
        mapping.update(dict(self.variables))
        expanded = Template(word).safe_substitute(mapping)
        return None if "$" in expanded else expanded


@dataclass(frozen=True)
class ShellCall:
    script: str
    workdir: str | None


def _codex_exec_argument(source: str) -> dict | None:
    """Read the object literal passed to Codex's `tools.exec_command({...})`."""
    start = source.find("exec_command(")
    if start < 0:
        return None
    brace = source.find("{", start)
    if brace < 0:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(source[brace:])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _script_from_argv(argv: list) -> str:
    words = [str(w) for w in argv]
    if len(words) >= 3 and os.path.basename(words[0]) in ("bash", "sh", "zsh") and words[1] in ("-c", "-lc"):
        return words[2]
    return shlex.join(words)


def shell_call_from_tool_input(tool_input: dict) -> ShellCall | None:
    """Extract the script and explicit working directory from any harness's shell tool input."""
    workdir = tool_input.get("workdir") or tool_input.get("cwd")
    command = tool_input.get("command")
    if command is None:
        command = tool_input.get("cmd")
    if isinstance(command, list):
        return ShellCall(_script_from_argv(command), workdir)
    if isinstance(command, str):
        return ShellCall(command, workdir)
    source = tool_input.get("input")
    if isinstance(source, str):
        argument = _codex_exec_argument(source)
        if argument is None:
            return None
        inner = argument.get("cmd") or argument.get("command")
        if isinstance(inner, list):
            inner = _script_from_argv(inner)
        if not isinstance(inner, str):
            return None
        return ShellCall(inner, argument.get("workdir") or workdir)
    return None


def _tokenize(line: str) -> list[str]:
    lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def _logical_lines(script: str) -> list[str]:
    lines: list[str] = []
    pending = ""
    for raw in script.split("\n"):
        if raw.endswith("\\") and not raw.endswith("\\\\"):
            pending += raw[:-1] + " "
            continue
        lines.append(pending + raw)
        pending = ""
    if pending:
        lines.append(pending)
    return lines


def _heredoc_delimiters(tokens: list[str]) -> list[tuple[str, bool]]:
    found = []
    for index, token in enumerate(tokens[:-1]):
        if token in HEREDOC_OPERATORS:
            delimiter = tokens[index + 1]
            strip_tabs = token == "<<-"
            if delimiter.startswith("-"):
                delimiter, strip_tabs = delimiter[1:], True
            if delimiter:
                found.append((delimiter, strip_tabs))
    return found


def _token_lines(script: str) -> list[list[str]] | None:
    """Tokenize each logical line, dropping heredoc bodies. None if any line cannot be lexed."""
    result: list[list[str]] = []
    waiting: list[tuple[str, bool]] = []
    for line in _logical_lines(script):
        if waiting:
            delimiter, strip_tabs = waiting[0]
            candidate = line.lstrip("\t") if strip_tabs else line
            if candidate.strip() == delimiter:
                waiting.pop(0)
            continue
        try:
            tokens = _tokenize(line)
        except ValueError:
            return None
        waiting.extend(_heredoc_delimiters(tokens))
        result.append(tokens)
    return result


def _is_assignment(word: str) -> bool:
    name, eq, _ = word.partition("=")
    return bool(eq) and name.replace("_", "a").isalnum() and not name[0].isdigit()


def parse_commands(call: ShellCall, session_cwd: str) -> list[Command] | None:
    """Split a shell call into commands, each tagged with the directory it runs in."""
    token_lines = _token_lines(call.script)
    if token_lines is None:
        return None
    base = call.workdir or session_cwd
    cwd = base if os.path.isabs(base) else os.path.join(session_cwd, base)
    commands: list[Command] = []
    variables: dict[str, str] = {}
    for tokens in token_lines:
        current: list[str] = []
        for token in tokens + [";"]:
            if token not in SEPARATORS:
                current.append(token)
                continue
            assignments = []
            while current and _is_assignment(current[0]):
                assignments.append(current.pop(0).partition("="))
            if assignments and not current:
                for name, _, value in assignments:
                    variables[name] = value
            if current:
                commands.append(Command(tuple(current), cwd, tuple(variables.items())))
                if current[0] == "cd" and len(current) > 1:
                    target = current[1]
                    cwd = target if os.path.isabs(target) else os.path.join(cwd, target)
            current = []
    return commands
