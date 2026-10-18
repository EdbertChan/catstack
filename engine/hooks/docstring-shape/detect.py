"""Find docstrings an edit leaves multi-line (outside a class) or over the length cap."""
from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

SDK_DIR = Path(__file__).resolve().parents[1] / "_sdk"
sys.path.insert(0, str(SDK_DIR))

from finding import Finding
from proposed_edit import ProposedEdit

RULE_DOCSTRING_SHAPE = "docstring-shape.multi-line-or-long"
RULE_UNCHECKED = "docstring-shape.unchecked"
MAX_DOCSTRING_CHARACTERS = 120
DOCUMENTED_NODES = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


@dataclass(frozen=True)
class DocstringHit:
    kind: str
    name: str
    line: int
    reason: str


class DocstringShapeCheck:
    """The docstrings one proposed edit to a Python file touches.

    The edit is applied in memory and the result is parsed.
    Every module, class and function docstring whose lines overlap an edited line is measured.
    A result that cannot be parsed, or a file that cannot be read, is unchecked rather than clean.
    """

    def __init__(self, edit: ProposedEdit) -> None:
        self.edit = edit
        self.path = edit.path
        self.unchecked_reason: str | None = None

    def applies(self) -> bool:
        return self.path.lower().endswith(".py")

    def run(self) -> list[DocstringHit]:
        if not self.edit.apply():
            self.unchecked_reason = self.edit.unchecked_reason
            return []
        return self.docstring_hits(self.edit.after or "", self.edit.edited_lines)

    def docstring_hits(self, text: str, edited: set[int]) -> list[DocstringHit]:
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError) as error:
            self.unchecked_reason = f"the edited {self.path} does not parse ({type(error).__name__}: {error}), so its docstrings were not checked"
            return []
        hits: list[DocstringHit] = []
        for node in ast.walk(tree):
            if not isinstance(node, DOCUMENTED_NODES):
                continue
            docstring_node = self.docstring_node(node)
            if docstring_node is None:
                continue
            span = range(docstring_node.lineno, (docstring_node.end_lineno or docstring_node.lineno) + 1)
            if not edited.intersection(span):
                continue
            reason = self.shape_problem(node, docstring_node.value.value, len(span))
            if reason:
                hits.append(DocstringHit(self.node_kind(node), self.node_name(node), docstring_node.lineno, reason))
        return hits

    def docstring_node(self, node: ast.AST) -> ast.Expr | None:
        body = getattr(node, "body", None)
        if not body or not isinstance(body[0], ast.Expr):
            return None
        value = body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return body[0]
        return None

    def shape_problem(self, node: ast.AST, docstring: str, source_lines: int) -> str | None:
        stripped = docstring.strip()
        if isinstance(node, ast.ClassDef):
            return None
        if "\n" in stripped:
            return f"spans {source_lines} lines; a docstring is one line that says what the thing is for"
        if len(stripped) > MAX_DOCSTRING_CHARACTERS:
            return f"is {len(stripped)} characters; the cap is {MAX_DOCSTRING_CHARACTERS}"
        return None

    def node_kind(self, node: ast.AST) -> str:
        if isinstance(node, ast.Module):
            return "module"
        if isinstance(node, ast.ClassDef):
            return "class"
        return "function"

    def node_name(self, node: ast.AST) -> str:
        if isinstance(node, ast.Module):
            return Path(self.path).name
        return getattr(node, "name", "?")

    def unchecked_finding(self) -> Finding:
        return Finding(
            rule_id=RULE_UNCHECKED,
            subject=self.path,
            message=f"docstring-shape: {self.unchecked_reason}",
            evidence=self.unchecked_reason or "",
        )

    def hit_finding(self, hits: list[DocstringHit]) -> Finding:
        shown = "\n".join(f"  {hit.kind} {hit.name} (line {hit.line}) {hit.reason}" for hit in hits[:5])
        message = (
            f"docstring-shape: this edit leaves {len(hits)} docstring(s) in {self.path} multi-line or over "
            f"{MAX_DOCSTRING_CHARACTERS} characters. A docstring is one line that says what the thing is for; "
            "how it works lives in the code. Only a class docstring may run several lines, one idea per line.\n" + shown
        )
        return Finding(
            rule_id=RULE_DOCSTRING_SHAPE,
            subject=self.path,
            message=message,
            evidence="\n".join(f"{hit.kind} {hit.name} line {hit.line}: {hit.reason}" for hit in hits),
        )


def detect(event: dict[str, object]) -> list[Finding]:
    edit = ProposedEdit.from_event(event)
    if edit is None:
        return []
    check = DocstringShapeCheck(edit)
    if not check.applies():
        return []
    hits = check.run()
    if check.unchecked_reason:
        edit.attach_unchecked(event, check.unchecked_finding())
        return []
    if not hits:
        return []
    return [check.hit_finding(hits)]


def decide(payload: dict) -> str | None:
    findings = detect(payload)
    if not findings:
        return None
    return "\n".join(finding.message for finding in findings)
