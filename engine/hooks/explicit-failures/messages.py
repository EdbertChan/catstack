"""Python error messages that do not name their cause, found with the `ast` parser.

Two shapes, both from principle-explicit-errors' "Error messages name their
cause" section:

- a vague raise: `raise X()` or `raise X("<text>")` where the message is a
  plain string (no f-string, no formatting, no second argument) made only of
  generic words such as "error", "failed", "invalid input". It names no value,
  no expectation, and no cause.
- a dropped cause: inside `except ... as err:`, a `raise Y(...)` with no
  `from` clause whose arguments never mention `err`. The original error is
  lost. `raise`, `raise ... from err` and `raise ... from None` are silent.

Source that does not parse as Python (a fragment, another language) yields
no hits; `ast` either reads the code or this detector stays out of it.
"""
from __future__ import annotations

import ast
import textwrap

ALLOW_MARK = "explicit-failures"
MESSAGE_PRINCIPLE = "error messages name their cause (principle-explicit-errors)"

GENERIC_WORDS = frozenset({
    "a", "an", "the", "is", "was", "has", "have", "been", "to", "of", "in", "on",
    "error", "errors", "failed", "failure", "fail", "fails", "invalid", "bad",
    "wrong", "something", "went", "occurred", "unexpected", "unknown", "oops",
    "problem", "issue", "input", "value", "data", "request", "operation",
    "exception", "could", "not", "cannot", "unable", "please", "try", "again",
})


def _parse(text: str) -> ast.Module | None:
    for candidate in (text, textwrap.dedent(text)):
        try:
            return ast.parse(candidate)
        except (SyntaxError, ValueError):
            continue
    return None


def _exception_name(node: ast.expr) -> str:
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return ""


def _is_generic(message: str) -> bool:
    words = [w.strip(".,:;!?()[]'\"-").lower() for w in message.split()]
    words = [w for w in words if w]
    return all(w in GENERIC_WORDS for w in words)


def _vague_message(exc: ast.expr) -> str | None:
    """The quoted message when the raise names no cause, else None."""
    if isinstance(exc, (ast.Name, ast.Attribute)):
        return "" if _exception_name(exc)[:1].isupper() else None
    if not isinstance(exc, ast.Call) or exc.keywords:
        return None
    if not exc.args:
        return ""
    if len(exc.args) != 1:
        return None
    arg = exc.args[0]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and _is_generic(arg.value):
        return arg.value
    return None


def _mentions(node: ast.AST, name: str) -> bool:
    return any(isinstance(n, ast.Name) and n.id == name for n in ast.walk(node))


def _allowed(lines: list[str], lineno: int) -> bool:
    here = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
    prev = lines[lineno - 2] if 1 < lineno <= len(lines) + 1 else ""
    return ALLOW_MARK in here or ALLOW_MARK in prev


class _Finder(ast.NodeVisitor):
    def __init__(self, lines: list[str]):
        self.lines = lines
        self.handlers: list[str] = []
        self.hits: list[tuple[int, str]] = []

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self.handlers.append(node.name or "")
        self.generic_visit(node)
        self.handlers.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        saved, self.handlers = self.handlers, []
        self.generic_visit(node)
        self.handlers = saved

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_Lambda = visit_FunctionDef

    def visit_Raise(self, node: ast.Raise) -> None:
        if node.exc is None or _allowed(self.lines, node.lineno):
            return
        name = _exception_name(node.exc) or "exception"
        message = _vague_message(node.exc)
        if message is not None:
            shown = f'{name}("{message}")' if message else f"{name}()"
            self.hits.append((node.lineno, f"`raise {shown}` names no cause, value, or expectation"))
        caught = self.handlers[-1] if self.handlers else ""
        if caught and node.cause is None and not _mentions(node.exc, caught):
            self.hits.append((node.lineno, f"`raise {name}(...)` inside `except ... as {caught}` drops `{caught}`; chain it with `from {caught}`"))


def scan_python_messages(text: str) -> list[tuple[int, str]]:
    """(1-based line, shape) for every error message that does not name its cause."""
    if not text:
        return []
    tree = _parse(text)
    if tree is None:
        return []
    finder = _Finder(text.splitlines())
    finder.visit(tree)
    return sorted(set(finder.hits))
