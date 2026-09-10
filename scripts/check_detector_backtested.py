#!/usr/bin/env python3
"""Fail a detector-pattern change whose PR body carries no Backtest block.

A change to a detector pattern is a change to what the repo can see.
Widening one on intuition fixes the phrasing someone imagined, never the
phrasings the corpus actually contains. This gate asks for the numbers.

It compares each changed Python file under engine/hooks/*/ (tests and
install_*.py excluded) and each scripts/check_*.py between the merge-base
and --head, by syntax tree rather than by diff text. A detector pattern is:

  - the pattern argument of any re.compile/search/match/fullmatch/findall/
    finditer/sub/subn/split call, anywhere in the file;
  - a module- or class-level UPPER_CASE constant bound to a regex, a number
    (a threshold), or a collection of literals (a pattern list);
  - an UPPER_CASE string constant that a regex pattern argument names.

When one of those differs, the PR body must hold a `## Backtest` section
with these key-value lines, filled from scripts/backtest_detector.py:

    Command: python3 scripts/backtest_detector.py --detector PATH:CALLABLE --compare REF
    Messages scanned: 1843
    Hits before: 12
    Hits after: 15
    Newly caught: 4
    Newly missed: 1
    False positives accepted: 1

Every value is a whole number, messages scanned is above zero, and the
numbers must agree: hits after - hits before == newly caught - newly
missed. Prose that mentions a backtest and some digits is not a block.

    python3 scripts/check_detector_backtested.py --body-file /tmp/pr.md
    python3 scripts/check_detector_backtested.py --base origin/main --head HEAD --body-file -

Exit 0 PASS: no detector pattern changed, or the block is present and valid.
Exit 1 FAIL: a detector pattern changed and the block is missing or invalid.
Exit 2 UNCHECKED: the base ref is not fetched, the diff or a changed file
cannot be read or parsed, or the PR body cannot be read. Never a pass.
"""
from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

PASS, FAIL, UNCHECKED = "PASS", "FAIL", "UNCHECKED"
EXIT_CODES = {PASS: 0, FAIL: 1, UNCHECKED: 2}

REGEX_FUNCS = frozenset({"compile", "search", "match", "fullmatch", "findall", "finditer", "sub", "subn", "split"})
LITERAL_CALLS = frozenset({"frozenset", "set", "tuple", "list", "dict"})
CONSTANT_NAME_RE = re.compile(r"^_*[A-Z][A-Z0-9_]*$")
EXEMPT_CONSTANTS = frozenset({"GATE_EXEMPLARS"})

HEADING_RE = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$")
FIELD_RE = re.compile(r"^\s*(?:[-*]\s+)?([A-Za-z][A-Za-z ]*?)\s*:\s*(.*?)\s*$")
COUNT_FIELDS = (
    "messages scanned",
    "hits before",
    "hits after",
    "newly caught",
    "newly missed",
    "false positives accepted",
)
COMMAND_FIELD = "command"
RUNNER = "backtest_detector.py"


def in_scope(path: str) -> bool:
    if not path.endswith(".py"):
        return False
    parts = path.split("/")
    if parts[:2] == ["engine", "hooks"] and len(parts) >= 4:
        name = parts[-1]
        return "tests" not in parts[3:-1] and not name.startswith(("test_", "install_"))
    return len(parts) == 2 and parts[0] == "scripts" and parts[1].startswith("check_")


def _regex_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "re"
        and node.func.attr in REGEX_FUNCS
        and bool(node.args)
    )


def _names_in(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _regex_named(tree: ast.AST) -> set[str]:
    named: set[str] = set()
    for node in ast.walk(tree):
        if _regex_call(node):
            named |= _names_in(node.args[0])
    return named


def _literal(node: ast.AST, constants: set[str]) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(_literal(e, constants) for e in node.elts)
    if isinstance(node, ast.Dict):
        return all(k is not None and _literal(k, constants) for k in node.keys) and all(
            _literal(v, constants) for v in node.values
        )
    if isinstance(node, ast.BinOp):
        return _literal(node.left, constants) and _literal(node.right, constants)
    if isinstance(node, ast.UnaryOp):
        return _literal(node.operand, constants)
    if isinstance(node, ast.Name):
        return node.id in constants
    if isinstance(node, ast.Attribute):
        return isinstance(node.value, ast.Name) and node.value.id == "re"
    if isinstance(node, ast.JoinedStr):
        return all(_literal(v, constants) for v in node.values)
    if isinstance(node, ast.FormattedValue):
        return _literal(node.value, constants)
    if isinstance(node, ast.Call):
        func = node.func
        callee_ok = (
            (isinstance(func, ast.Name) and func.id in LITERAL_CALLS)
            or _regex_call(node)
            or (isinstance(func, ast.Attribute) and _literal(func.value, constants))
        )
        return callee_ok and all(_literal(a, constants) for a in node.args) and all(
            _literal(k.value, constants) for k in node.keywords
        )
    return False


def _pattern_kind(value: ast.AST, name: str, regex_named: set[str], constants: set[str]) -> bool:
    if not _literal(value, constants):
        return False
    if isinstance(value, ast.Constant):
        if isinstance(value.value, bool) or value.value is None:
            return False
        if isinstance(value.value, (str, bytes)):
            return name in regex_named
        return True
    if isinstance(value, ast.JoinedStr):
        return name in regex_named
    return True


def _assignments(body: list[ast.stmt], prefix: str = ""):
    for stmt in body:
        if isinstance(stmt, ast.ClassDef):
            yield from _assignments(stmt.body, f"{prefix}{stmt.name}.")
            continue
        if isinstance(stmt, ast.Assign):
            targets, value = stmt.targets, stmt.value
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            targets, value = [stmt.target], stmt.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and CONSTANT_NAME_RE.match(target.id):
                yield target.id, f"{prefix}{target.id}", stmt, value


@dataclass
class Patterns:
    constants: dict[str, str] = field(default_factory=dict)
    inline: Counter = field(default_factory=Counter)
    inline_where: dict[str, tuple[int, str]] = field(default_factory=dict)


def extract(source: str | None) -> Patterns:
    found = Patterns()
    if source is None:
        return found
    tree = ast.parse(source)
    regex_named = _regex_named(tree)
    known: set[str] = set()
    covered: set[int] = set()
    for bare, qualified, stmt, value in _assignments(tree.body):
        if bare in EXEMPT_CONSTANTS:
            covered.add(id(stmt))
            continue
        if _pattern_kind(value, bare, regex_named, known):
            known.add(bare)
            found.constants[qualified] = ast.dump(value)
            covered.add(id(stmt))
    skip = {id(n) for stmt in ast.walk(tree) if id(stmt) in covered for n in ast.walk(stmt)}
    for node in ast.walk(tree):
        if id(node) in skip or not _regex_call(node):
            continue
        dump = ast.dump(node.args[0])
        found.inline[dump] += 1
        found.inline_where.setdefault(dump, (node.lineno, f"re.{node.func.attr}()"))
    return found


def changed_patterns(before: str | None, after: str | None) -> list[str]:
    old, new = extract(before), extract(after)
    changed = sorted(
        name for name in old.constants.keys() | new.constants.keys() if old.constants.get(name) != new.constants.get(name)
    )
    added = new.inline - old.inline
    removed = old.inline - new.inline
    for dump in sorted(added, key=lambda d: new.inline_where[d]):
        line, call = new.inline_where[dump]
        changed.append(f"{call} pattern at line {line}")
    if removed and not added:
        changed.append(f"{sum(removed.values())} inline re pattern(s) removed")
    return changed


@dataclass
class BlockResult:
    present: bool
    problems: list[str]
    values: dict[str, int]


def backtest_section(body: str) -> list[str] | None:
    lines = body.splitlines()
    for i, line in enumerate(lines):
        m = HEADING_RE.match(line)
        if m and m.group(1).strip().lower() == "backtest":
            level = len(line) - len(line.lstrip("#"))
            section = []
            for rest in lines[i + 1:]:
                h = HEADING_RE.match(rest)
                if h and len(rest) - len(rest.lstrip("#")) <= level:
                    break
                section.append(rest)
            return section
    return None


def parse_block(body: str) -> BlockResult:
    section = backtest_section(body)
    if section is None:
        return BlockResult(False, ["no `## Backtest` section in the PR body"], {})
    seen: dict[str, list[str]] = {}
    for line in section:
        m = FIELD_RE.match(line)
        if not m:
            continue
        key = " ".join(m.group(1).lower().split())
        if key in COUNT_FIELDS or key == COMMAND_FIELD:
            seen.setdefault(key, []).append(m.group(2))
    problems: list[str] = []
    values: dict[str, int] = {}
    for key in (COMMAND_FIELD, *COUNT_FIELDS):
        raw = seen.get(key)
        if not raw:
            problems.append(f"missing field `{key.capitalize()}:`")
            continue
        if len(raw) > 1:
            problems.append(f"field `{key.capitalize()}:` appears {len(raw)} times")
            continue
        if key == COMMAND_FIELD:
            if RUNNER not in raw[0]:
                problems.append(f"`Command:` does not run scripts/{RUNNER}: {raw[0]!r}")
            continue
        text = raw[0].strip("`").strip()
        if not (text.isascii() and text.isdigit()):
            problems.append(f"`{key.capitalize()}:` is not a whole number: {raw[0]!r}")
            continue
        values[key] = int(text)
    if len(values) == len(COUNT_FIELDS):
        problems += _consistency(values)
    return BlockResult(True, problems, values)


def _consistency(v: dict[str, int]) -> list[str]:
    problems = []
    if v["messages scanned"] == 0:
        problems.append("messages scanned is 0; a backtest over nothing proves nothing")
    if v["hits after"] - v["hits before"] != v["newly caught"] - v["newly missed"]:
        problems.append(
            "numbers disagree: hits after - hits before "
            f"({v['hits after']} - {v['hits before']}) != newly caught - newly missed "
            f"({v['newly caught']} - {v['newly missed']})"
        )
    for part, whole in (("hits before", "messages scanned"), ("hits after", "messages scanned"),
                        ("newly caught", "hits after"), ("newly missed", "hits before"),
                        ("false positives accepted", "hits after")):
        if v[part] > v[whole]:
            problems.append(f"{part} ({v[part]}) exceeds {whole} ({v[whole]})")
    return problems


@dataclass
class Verdict:
    outcome: str
    lines: list[str]


def decide(touched: dict[str, list[str]], unreadable: list[str], body: str | None, body_error: str | None) -> Verdict:
    if body_error is not None:
        return Verdict(UNCHECKED, [f"PR body cannot be read: {body_error}"])
    if not touched and not unreadable:
        return Verdict(PASS, ["no detector pattern changed"])
    listed = [f"{path}: {', '.join(names)}" for path, names in sorted(touched.items())]
    listed += [f"{note} (could not compare patterns)" for note in unreadable]
    if body is None:
        return Verdict(UNCHECKED, ["no PR body supplied (--body-file), and it is needed for:"] + listed)
    block = parse_block(body)
    if block.present and not block.problems:
        v = block.values
        return Verdict(PASS, [
            f"Backtest block present: scanned={v['messages scanned']} before={v['hits before']} "
            f"after={v['hits after']} caught={v['newly caught']} missed={v['newly missed']} "
            f"accepted_fp={v['false positives accepted']}"
        ] + listed)
    if not touched:
        return Verdict(UNCHECKED, ["a changed detector file could not be compared, and no valid Backtest block covers it:"] + listed + block.problems)
    return Verdict(FAIL, ["detector pattern changed without a valid Backtest block:"] + listed + block.problems)


def compare_file(path: str, before: str | None, after: str | None, touched: dict[str, list[str]], unreadable: list[str]) -> None:
    try:
        names = changed_patterns(before, after)
    except SyntaxError as exc:
        unreadable.append(f"{path}: SyntaxError line {exc.lineno}")
        return
    if names:
        touched[path] = names


def evaluate_sources(path: str, before: str | None, after: str | None, body: str | None) -> Verdict:
    touched: dict[str, list[str]] = {}
    unreadable: list[str] = []
    if in_scope(path):
        compare_file(path, before, after, touched, unreadable)
    return decide(touched, unreadable, body, None)


GATE_EXEMPLARS: dict[str, list[tuple[str, str | None, str | None, str]]] = {
    "catch": [
        (
            "engine/hooks/hedge/detect.py",
            'import re\nHEDGE_RE = re.compile(r"\\bshould\\b")\n',
            'import re\nHEDGE_RE = re.compile(r"\\b(?:should|ought to)\\b")\n',
            "## Summary\n\nWiden the hedge regex to catch ought to.\n",
        ),
        (
            "scripts/check_history_claims.py",
            "WINDOW = 6\n",
            "WINDOW = 8\n",
            "## Backtest\n\nRan the backtest over 1200 messages, 3 new hits, 0 misses, looks fine.\n",
        ),
        (
            "engine/hooks/diu-stop/claude_stop_check.py",
            "BANNED_OPENERS = ['confirmed', 'verified']\n",
            "BANNED_OPENERS = ['confirmed', 'verified', 'done']\n",
            "## Backtest\n\nCommand: python3 scripts/backtest_detector.py --detector x.py:f\n"
            "Messages scanned: 900\nHits before: 4\nHits after: 9\nNewly caught: 2\n"
            "Newly missed: 0\nFalse positives accepted: 0\n",
        ),
        (
            "engine/hooks/scope-lock/detect.py",
            'import re\n_VERB = "(?:do|use)"\nRX = re.compile(rf"\\b{_VERB}\\b")\n',
            'import re\n_VERB = "(?:do|use|run)"\nRX = re.compile(rf"\\b{_VERB}\\b")\n',
            "",
        ),
    ],
    "allow": [
        (
            "engine/hooks/hedge/detect.py",
            'import re\nHEDGE_RE = re.compile(r"\\bshould\\b")\n',
            'import re\nHEDGE_RE = re.compile(r"\\b(?:should|ought to)\\b")\n',
            "## Backtest\n\n- Command: python3 scripts/backtest_detector.py --detector engine/hooks/hedge/detect.py:hit "
            "--compare origin/main\n- Messages scanned: 1843\n- Hits before: 12\n- Hits after: 15\n"
            "- Newly caught: 4\n- Newly missed: 1\n- False positives accepted: 1\n",
        ),
        (
            "engine/hooks/hedge/detect.py",
            'MESSAGE = "hedge: prove it"\n',
            'MESSAGE = "hedge: run the check and paste it"\n',
            "## Summary\n\nReword the block message.\n",
        ),
        (
            "engine/hooks/hedge/tests/test_hooks.py",
            'import re\nRX = re.compile(r"a")\n',
            'import re\nRX = re.compile(r"b")\n',
            "",
        ),
        (
            "engine/hooks/hedge/install_claude_hook.py",
            "TIMEOUT = 5\n",
            "TIMEOUT = 10\n",
            "",
        ),
    ],
}


def gate_check(exemplar: tuple[str, str | None, str | None, str]) -> bool:
    path, before, after, body = exemplar
    verdict = evaluate_sources(path, before, after, body)
    if verdict.outcome == UNCHECKED:
        raise ValueError(f"exemplar is undecidable: {verdict.lines}")
    return verdict.outcome == FAIL


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True)


def _show(ref: str, path: str) -> tuple[str | None, str | None]:
    res = _git("show", f"{ref}:{path}")
    if res.returncode != 0:
        return None, res.stderr.strip() or f"git show {ref}:{path} exited {res.returncode}"
    return res.stdout, None


def collect(base: str, head: str) -> tuple[dict[str, list[str]], list[str], str | None]:
    for ref in (base, head):
        if _git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").returncode != 0:
            return {}, [], f"ref {ref!r} is not fetched here"
    mb = _git("merge-base", base, head)
    if mb.returncode != 0:
        return {}, [], f"no merge-base between {base} and {head}: {mb.stderr.strip()}"
    fork = mb.stdout.strip()
    diff = _git("diff", "--name-status", "--no-renames", "-z", fork, head)
    if diff.returncode != 0:
        return {}, [], f"git diff failed: {diff.stderr.strip()}"
    fields = diff.stdout.split("\0")
    touched: dict[str, list[str]] = {}
    unreadable: list[str] = []
    for status, path in zip(fields[0::2], fields[1::2]):
        if not path or not in_scope(path):
            continue
        before, before_err = (None, None) if status == "A" else _show(fork, path)
        after, after_err = (None, None) if status == "D" else _show(head, path)
        if before_err or after_err:
            unreadable.append(f"{path}: {before_err or after_err}")
            continue
        compare_file(path, before, after, touched, unreadable)
    return touched, unreadable, None


def read_body(spec: str | None) -> tuple[str | None, str | None]:
    if spec is None:
        return None, None
    try:
        if spec == "-":
            return sys.stdin.read(), None
        return Path(spec).read_text(encoding="utf-8"), None
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--body-file", help="PR body markdown, or - for stdin")
    args = ap.parse_args(argv)
    body, body_error = read_body(args.body_file)
    touched, unreadable, diff_error = collect(args.base, args.head)
    if diff_error is not None:
        verdict = Verdict(UNCHECKED, [f"diff cannot be read: {diff_error}"])
    else:
        verdict = decide(touched, unreadable, body, body_error)
    stream = sys.stdout if verdict.outcome == PASS else sys.stderr
    print(f"{verdict.outcome} detector-backtested: {verdict.lines[0]}", file=stream)
    for line in verdict.lines[1:]:
        print(f"  {line}", file=stream)
    return EXIT_CODES[verdict.outcome]


if __name__ == "__main__":
    raise SystemExit(main())
