"""Find abbreviated or two-letter names an edit introduces in a Python file or in a new file's name."""
from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

SDK_DIR = Path(__file__).resolve().parents[1] / "_sdk"
sys.path.insert(0, str(SDK_DIR))

from finding import Finding
from proposed_edit import ProposedEdit

RULE_SHORT_NAME = "short-name.abbreviated-name"
RULE_UNCHECKED = "short-name.unchecked"
ACCEPTED_SHORT_WORDS = (
    "id", "db", "url", "api", "cli", "csv", "sql", "git", "run", "add", "get", "set", "key", "max", "min",
    "end", "row", "col", "tag", "ref", "sha", "cls", "app", "pid", "iso", "out", "err", "log", "top", "low",
    "raw", "hop", "job", "gap", "seq", "pct", "sum", "ago", "now", "new", "old", "lhs", "rhs",
)
ENGLISH_SHORT_WORDS = (
    "a", "is", "to", "in", "on", "by", "as", "at", "of", "or", "no", "up", "do", "if", "go", "ok", "an",
    "be", "it", "so", "we", "me", "my", "us", "am", "and", "any", "all", "for", "has", "not", "one", "per",
    "two", "six", "ten", "use", "via", "own", "the", "off", "map", "can", "how", "who", "why", "was", "are",
    "few", "bit", "day", "its", "hit", "non", "def", "act", "age", "aim", "air", "arm", "art", "ask", "bad",
    "bag", "bar", "bay", "bed", "bet", "big", "bin", "bus", "buy", "car", "cat", "cup", "cut", "dog", "dot",
    "dry", "due", "eat", "egg", "era", "eye", "fan", "far", "fat", "fee", "fit", "fix", "fly", "fun", "gas",
    "had", "hat", "her", "him", "his", "hot", "ice", "ill", "jar", "joy", "kid", "kit", "lab", "law", "lay",
    "leg", "let", "lid", "lie", "lit", "lot", "man", "men", "met", "mid", "mix", "net", "nor", "odd", "oil",
    "our", "owe", "pad", "pan", "pay", "pen", "pet", "pin", "pit", "pop", "pot", "put", "ran", "red", "rid",
    "rip", "rod", "rot", "sad", "sat", "saw", "say", "sea", "see", "sit", "sky", "son", "sun", "tab", "tax",
    "tea", "tie", "tin", "tip", "toe", "too", "toy", "try", "van", "war", "way", "web", "wet", "win", "won",
    "yes", "yet", "you", "zip",
)
DENIED_ABBREVIATIONS = (
    "preds", "topo", "recs", "resp", "proj", "iid", "dur", "nid", "cfg", "dd", "gl", "cnt", "idx", "tmp",
    "buf", "msg", "msgs", "params",
)
NAME_EXAMPLES = "datadog not dd, config not cfg, epoch_seconds not ts"


@dataclass(frozen=True)
class NameHit:
    kind: str
    name: str
    line: int
    reason: str


class ShortNameCheck:
    """The names one proposed edit introduces or changes.

    Covers def and class names, parameters, attribute assignments and class-body fields in a Python file,
    plus the file stem when Write creates a new file of any kind.
    Loop variables, comprehension targets, lambda parameters and dunder names are out of scope.
    """

    def __init__(self, edit: ProposedEdit) -> None:
        self.edit = edit
        self.path = edit.path
        self.unchecked_reason: str | None = None

    def applies(self) -> bool:
        return self.path.lower().endswith(".py") or self.edit.creates_file()

    def run(self) -> list[NameHit]:
        hits: list[NameHit] = []
        if self.edit.creates_file():
            reason = self.name_problem(Path(self.path).stem)
            if reason:
                hits.append(NameHit("file", Path(self.path).name, 0, reason))
        if not self.path.lower().endswith(".py"):
            return hits
        if not self.edit.apply():
            self.unchecked_reason = self.edit.unchecked_reason
            return hits
        return hits + self.code_hits(self.edit.after or "", self.edit.edited_lines)

    def name_problem(self, name: str) -> str | None:
        if name.startswith("__") and name.endswith("__"):
            return None
        for part in [part for part in name.lstrip("_").split("_") if part]:
            lowered = part.lower()
            if lowered.isdigit():
                continue
            if lowered in DENIED_ABBREVIATIONS:
                return f"'{part}' is an abbreviation; spell it out"
            if lowered in ACCEPTED_SHORT_WORDS or lowered in ENGLISH_SHORT_WORDS:
                continue
            if len(lowered) <= 2:
                return f"'{part}' is {len(lowered)} letter(s); spell the name out"
            if len(lowered) == 3:
                return f"'{part}' is three letters and not an accepted word; spell it out"
        return None

    def code_hits(self, text: str, edited: set[int]) -> list[NameHit]:
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError) as error:
            self.unchecked_reason = f"the edited {self.path} does not parse ({type(error).__name__}: {error}), so its names were not checked"
            return []
        hits: list[NameHit] = []
        for kind, name, line in self.introduced_names(tree):
            if line not in edited:
                continue
            reason = self.name_problem(name)
            if reason:
                hits.append(NameHit(kind, name, line, reason))
        return hits

    def introduced_names(self, tree: ast.AST) -> list[tuple[str, str, int]]:
        names: list[tuple[str, str, int]] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.append(("function", node.name, node.lineno))
                names.extend(("parameter", argument.arg, argument.lineno) for argument in self.parameters(node.args))
            elif isinstance(node, ast.ClassDef):
                names.append(("class", node.name, node.lineno))
                names.extend(self.class_fields(node))
            elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                names.extend(self.attribute_targets(node))
        return names

    def parameters(self, arguments: ast.arguments) -> list[ast.arg]:
        found = list(arguments.posonlyargs) + list(arguments.args) + list(arguments.kwonlyargs)
        found.extend(argument for argument in (arguments.vararg, arguments.kwarg) if argument is not None)
        return found

    def class_fields(self, node: ast.ClassDef) -> list[tuple[str, str, int]]:
        fields: list[tuple[str, str, int]] = []
        for statement in node.body:
            if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                fields.append(("attribute", statement.target.id, statement.lineno))
            elif isinstance(statement, ast.Assign):
                fields.extend(("attribute", target.id, target.lineno) for target in statement.targets if isinstance(target, ast.Name))
        return fields

    def attribute_targets(self, node: ast.Assign | ast.AnnAssign | ast.AugAssign) -> list[tuple[str, str, int]]:
        targets = list(node.targets) if isinstance(node, ast.Assign) else [node.target]
        found: list[tuple[str, str, int]] = []
        for target in targets:
            for leaf in ast.walk(target):
                if isinstance(leaf, ast.Attribute) and isinstance(leaf.ctx, ast.Store):
                    found.append(("attribute", leaf.attr, leaf.lineno))
        return found

    def unchecked_finding(self) -> Finding:
        return Finding(
            rule_id=RULE_UNCHECKED,
            subject=self.path,
            message=f"short-name: {self.unchecked_reason}",
            evidence=self.unchecked_reason or "",
        )

    def hit_finding(self, hits: list[NameHit]) -> Finding:
        shown = "\n".join(f"  {hit.kind} {hit.name} (line {hit.line}) {hit.reason}" for hit in hits[:8])
        message = (
            f"short-name: this edit introduces {len(hits)} abbreviated or short name(s) in {self.path}. "
            f"Names are spelled out ({NAME_EXAMPLES}); a one- or two-letter part is wrong and a three-letter "
            "part needs to be an accepted word.\n" + shown
        )
        return Finding(
            rule_id=RULE_SHORT_NAME,
            subject=self.path,
            message=message,
            evidence="\n".join(f"{hit.kind} {hit.name} line {hit.line}: {hit.reason}" for hit in hits),
        )


def detect(event: dict[str, object]) -> list[Finding]:
    edit = ProposedEdit.from_event(event)
    if edit is None:
        return []
    check = ShortNameCheck(edit)
    if not check.applies():
        return []
    hits = check.run()
    if check.unchecked_reason:
        edit.attach_unchecked(event, check.unchecked_finding())
    if not hits:
        return []
    return [check.hit_finding(hits)]


def decide(payload: dict) -> str | None:
    findings = detect(payload)
    if not findings:
        return None
    return "\n".join(finding.message for finding in findings)
