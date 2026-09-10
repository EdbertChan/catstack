"""Decide what an inline Python or Node program does to Invoker's database.

Python is parsed, not grepped: `db = '.../invoker.db'` then
`sqlite3.connect(db)` has to resolve through the variable, and a program
that reads Invoker's database read-only while writing a scratch database
must not be charged with the scratch writes. Node gets a coarser text read.

Each function returns a `Verdict` or None when the program never opens
Invoker's database.
"""
from __future__ import annotations

import ast
import re

from statements import WRITE, classify_sql, looks_like_sql

DB_BASENAMES = ("invoker.db", "invoker.db-wal", "invoker.db-shm")
MENTION_RE = re.compile(r"(?<![\w.-])invoker\.db(?:-wal|-shm)?(?![\w.-])")
CONFIG_KEYS = {
    "executionAgent": "agent",
    "poolId": "pool",
    "poolMemberId": "pool",
    "runnerKind": "executor",
    "remoteTargetId": "executor",
}
EXECUTE_ATTRS = {"execute", "executemany", "executescript"}
PATH_FUNCS = {"expanduser", "expandvars", "join", "abspath", "realpath", "normpath", "Path", "PurePath", "str", "fspath", "resolve"}
OPAQUE_FUNCS = {"getenv", "input", "get"}
SQLITE_API_RE = re.compile(r"node:sqlite|better-sqlite3|\bsqlite3\b|DatabaseSync|\bnew\s+Database\b")
READONLY_RE = re.compile(r"readOnly\s*:\s*true|readonly\s*:\s*true|[?&]mode=ro\b|OPEN_READONLY", re.IGNORECASE)
JS_STRING_RE = re.compile(r"'((?:[^'\\\n]|\\.)*)'|\"((?:[^\"\\\n]|\\.)*)\"|`((?:[^`\\]|\\.)*)`", re.DOTALL)


class Verdict:
    """What one command stage does to Invoker's database."""

    __slots__ = ("outcome", "path", "writes", "why", "read_write_open", "config_kinds", "file_op")

    def __init__(self, outcome, path, writes=(), why="", read_write_open=False, config_kinds=(), file_op=""):
        self.outcome = outcome
        self.path = path
        self.writes = list(writes)
        self.why = why
        self.read_write_open = read_write_open
        self.config_kinds = sorted(set(config_kinds))
        self.file_op = file_op


def db_path(text):
    """`text` when it names Invoker's database file (any spelling of the dir), else None."""
    if not text:
        return None
    bare = text[5:] if text.startswith("file:") else text
    bare = bare.split("?", 1)[0].rstrip("/")
    return text if bare.rsplit("/", 1)[-1] in DB_BASENAMES else None


def mentioned_path(text):
    match = MENTION_RE.search(text or "")
    if not match:
        return None
    start = match.start()
    while start > 0 and text[start - 1] not in " \t\n'\"`(,=":
        start -= 1
    return text[start:match.end()]


def config_kinds_in(text):
    return {kind for key, kind in CONFIG_KEYS.items() if re.search(r"\b" + key + r"\b", text or "")}


class _Python:
    def __init__(self, tree):
        self.tree = tree
        self.assigns = {}
        self.imported = set()
        self.sqlite_modules = {"sqlite3"}
        self.connect_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.imported.add((alias.asname or alias.name).split(".")[0])
                    if alias.name == "sqlite3":
                        self.sqlite_modules.add(alias.asname or "sqlite3")
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    self.imported.add(alias.asname or alias.name)
                    if node.module == "sqlite3" and alias.name == "connect":
                        self.connect_names.add(alias.asname or "connect")
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.assigns.setdefault(target.id, []).append(node.value)
            elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and isinstance(node.target, ast.Name) and node.value is not None:
                self.assigns.setdefault(node.target.id, []).append(node.value)
            elif isinstance(node, ast.withitem) and isinstance(node.optional_vars, ast.Name):
                self.assigns.setdefault(node.optional_vars.id, []).append(node.context_expr)

    def texts(self, node, depth=0):
        """(candidate strings, fully resolved?) an expression can evaluate to."""
        if depth > 6 or node is None:
            return [], False
        if isinstance(node, ast.Constant):
            return ([node.value] if isinstance(node.value, str) else []), True
        if isinstance(node, ast.JoinedStr):
            parts, complete = [], True
            for value in node.values:
                if isinstance(value, ast.Constant):
                    parts.append(str(value.value))
                    continue
                inner, ok = self.texts(value.value, depth + 1)
                parts.append(inner[0] if len(inner) == 1 else "?")
                complete = complete and ok and len(inner) == 1
            return ["".join(parts)], complete
        if isinstance(node, ast.BinOp):
            left, lok = self.texts(node.left, depth + 1)
            right, rok = self.texts(node.right, depth + 1)
            sep = "/" if isinstance(node.op, ast.Div) else ""
            if isinstance(node.op, ast.Mod):
                return left, lok and rok
            joined = [a + sep + b for a in (left or [""]) for b in (right or [""])][:8]
            return joined, lok and rok
        if isinstance(node, ast.Name):
            if node.id in self.assigns:
                out, complete = [], True
                for value in self.assigns[node.id]:
                    inner, ok = self.texts(value, depth + 1)
                    out.extend(inner)
                    complete = complete and ok
                return out, complete
            return [], node.id in self.imported or node.id in ("True", "False", "None")
        if isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            pieces, complete = [], name not in OPAQUE_FUNCS
            for arg in node.args:
                inner, ok = self.texts(arg, depth + 1)
                pieces.append(inner)
                complete = complete and ok
            if name in ("join",) and pieces and all(len(p) == 1 for p in pieces):
                return ["/".join(p[0] for p in pieces)], complete
            flat = [text for piece in pieces for text in piece]
            if name in PATH_FUNCS and isinstance(node.func, ast.Attribute):
                inner, ok = self.texts(node.func.value, depth + 1)
                flat = [a + ("/" if a and b else "") + b for a in (inner or [""]) for b in (flat or [""])]
                complete = complete and ok
            return flat, complete
        if isinstance(node, ast.Attribute):
            inner, ok = self.texts(node.value, depth + 1)
            return inner, ok
        if isinstance(node, ast.Subscript):
            return [], False
        return [], False

    def is_connect(self, call):
        func = call.func
        if isinstance(func, ast.Attribute) and func.attr == "connect":
            return isinstance(func.value, ast.Name) and func.value.id in self.sqlite_modules
        return isinstance(func, ast.Name) and func.id in self.connect_names

    def connection_of(self, node, conns, depth=0):
        """The connect() call a receiver expression came from, or None."""
        if depth > 6 or node is None:
            return None
        if isinstance(node, ast.Call):
            if self.is_connect(node):
                return conns.get(id(node))
            if isinstance(node.func, ast.Attribute) and node.func.attr in ("cursor", "execute", "executemany", "executescript"):
                return self.connection_of(node.func.value, conns, depth + 1)
            return None
        if isinstance(node, ast.Name):
            for value in self.assigns.get(node.id, []):
                found = self.connection_of(value, conns, depth + 1)
                if found is not None:
                    return found
        return None


class _Conn:
    __slots__ = ("target", "path", "read_only")

    def __init__(self, target, path, read_only):
        self.target = target
        self.path = path
        self.read_only = read_only


def _connect_args(call):
    node = call.args[0] if call.args else next((k.value for k in call.keywords if k.arg == "database"), None)
    uri = any(k.arg == "uri" and isinstance(k.value, ast.Constant) and k.value.value is True for k in call.keywords)
    return node, uri


def classify_python(program, cmdline_mentions=None):
    """Verdict for an inline Python program, or None when it leaves the database alone."""
    try:
        tree = ast.parse(program)
    except (SyntaxError, ValueError) as exc:
        return classify_program_text(program, cmdline_mentions, unparsed=f"the Python program did not parse ({exc.__class__.__name__})")
    py = _Python(tree)
    conns = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and py.is_connect(node):
            arg, uri = _connect_args(node)
            texts, complete = py.texts(arg)
            path = next((t for t in texts if db_path(t) or mentioned_path(t)), None)
            if path:
                target = True
            else:
                target = False if complete else None
            read_only = uri and any(re.search(r"[?&](mode=ro|immutable=1)\b", t) for t in texts)
            conns[id(node)] = _Conn(target, path, read_only)
    mention = mentioned_path(program) or cmdline_mentions
    writes = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in EXECUTE_ATTRS):
            continue
        conn = py.connection_of(node.func.value, conns)
        if conn is not None and conn.target is False:
            continue
        texts, _ = py.texts(node.args[0] if node.args else None)
        for text in texts:
            writes.extend(s for s in classify_sql(text) if s.kind == WRITE)
    targets = [c for c in conns.values() if c.target is True]
    unresolved = [c for c in conns.values() if c.target is None and not c.read_only]
    if targets:
        path = targets[0].path
        read_write = any(not c.read_only for c in targets)
        if writes or read_write:
            kinds = config_kinds_in(program) if any("config" in w.columns for w in writes) else set()
            return Verdict("hit", path, writes, read_write_open=read_write and not writes, config_kinds=kinds)
        return Verdict("clean", path)
    if unresolved and mention:
        return Verdict("unchecked", mention, why="it opens a SQLite database whose path the guard could not resolve, and the program names Invoker's database")
    return None


def classify_program_text(program, cmdline_mentions=None, unparsed=""):
    """Coarse verdict from program text: Node, or Python that did not parse."""
    mention = mentioned_path(program) or cmdline_mentions
    if not mention or not SQLITE_API_RE.search(program or ""):
        return None
    writes = []
    for match in JS_STRING_RE.finditer(program):
        literal = next(g for g in match.groups() if g is not None)
        if looks_like_sql(literal):
            writes.extend(s for s in classify_sql(literal) if s.kind == WRITE)
    if writes:
        kinds = config_kinds_in(program) if any("config" in w.columns for w in writes) else set()
        return Verdict("hit", mention, writes, config_kinds=kinds)
    if READONLY_RE.search(program):
        return Verdict("clean", mention)
    if unparsed:
        return Verdict("unchecked", mention, why=unparsed)
    return Verdict("hit", mention, read_write_open=True)

