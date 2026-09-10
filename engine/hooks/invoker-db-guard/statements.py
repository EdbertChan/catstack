"""Sort SQL text into writes, reads, and statements the guard cannot vouch for.

Read-only is granted, not assumed: a statement is a read only when its
leading keyword is on the read list, or it is a PRAGMA the list names. A
keyword on neither list is `unknown`, which the caller reports as unchecked
rather than clean.
"""
from __future__ import annotations

import re

WRITE = "write"
READ = "read"
UNKNOWN = "unknown"

WRITE_HEADS = {
    "ALTER", "ANALYZE", "CREATE", "DELETE", "DROP", "INSERT", "REINDEX",
    "REPLACE", "UPDATE", "UPSERT", "VACUUM",
}
READ_HEADS = {
    "ATTACH", "BEGIN", "COMMIT", "DETACH", "END", "EXPLAIN", "RELEASE",
    "ROLLBACK", "SAVEPOINT", "SELECT", "VALUES",
}
CONNECTION_PRAGMAS = {
    "analysis_limit", "automatic_index", "busy_timeout", "cache_size",
    "case_sensitive_like", "cell_size_check", "count_changes",
    "defer_foreign_keys", "empty_result_callbacks", "foreign_keys",
    "full_column_names", "hard_heap_limit", "ignore_check_constraints",
    "legacy_alter_table", "mmap_size", "query_only", "recursive_triggers",
    "reverse_unordered_selects", "short_column_names", "shrink_memory",
    "soft_heap_limit", "synchronous", "temp_store", "threads", "trusted_schema",
}
TABLE_ARG_PRAGMAS = {
    "foreign_key_check", "foreign_key_list", "index_info", "index_list",
    "index_xinfo", "integrity_check", "quick_check", "table_info", "table_list",
    "table_xinfo",
}
QUERY_PRAGMAS = {
    "application_id", "auto_vacuum", "collation_list", "compile_options",
    "data_version", "database_list", "encoding", "freelist_count",
    "function_list", "journal_mode", "max_page_count", "module_list",
    "page_count", "page_size", "pragma_list", "schema_version", "secure_delete",
    "user_version",
}
FILE_ACTION_PRAGMAS = {"incremental_vacuum", "optimize", "wal_checkpoint"}
READ_DOTS = {
    "backup", "bail", "changes", "databases", "dbinfo", "dump", "echo", "eqp",
    "exit", "explain", "fullschema", "header", "headers", "help", "indexes",
    "indices", "mode", "nullvalue", "once", "output", "print", "prompt",
    "quit", "save", "schema", "separator", "show", "stats", "tables", "timeout",
    "timer", "width",
}
WRITE_DOTS = {"import", "restore"}

LITERAL_OR_COMMENT_RE = re.compile(r"'(?:[^']|'')*'|--[^\n]*|/\*.*?\*/", re.DOTALL)
WORD_RE = re.compile(r"[A-Za-z_]\w*")
PRAGMA_RE = re.compile(r"PRAGMA\s+(?:[\w\"`\[\]]+\.)?[\"`\[]?(\w+)[\"`\]]?\s*(=|\()?", re.IGNORECASE)
UPDATE_RE = re.compile(
    r"\bUPDATE\s+(?:OR\s+\w+\s+)?([\w\"`\[\].]+)\s+SET\s+(.*?)(?:\bWHERE\b|\bFROM\b|\bRETURNING\b|$)",
    re.IGNORECASE | re.DOTALL,
)
SET_COLUMN_RE = re.compile(r"(?:^|,)\s*[\"`\[]?(\w+)[\"`\]]?\s*=", re.DOTALL)
DELETE_RE = re.compile(r"\bDELETE\s+FROM\s+([\w\"`\[\].]+)", re.IGNORECASE)
INSERT_RE = re.compile(r"\b(INSERT|REPLACE)\s+(?:OR\s+\w+\s+)?INTO\s+([\w\"`\[\].]+)", re.IGNORECASE)
OBJECT_RE = re.compile(r"\b(DROP|ALTER|CREATE)\s+(?:TEMP\w*\s+|UNIQUE\s+)?(\w+)\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?([\w\"`\[\].]+)", re.IGNORECASE)
WITH_WRITE_RE = re.compile(r"\b(UPDATE|INSERT|DELETE|REPLACE)\b", re.IGNORECASE)


class Statement:
    """One classified statement, plus what it changes when it is a write."""

    __slots__ = ("kind", "text", "verb", "table", "columns")

    def __init__(self, kind, text, verb="", table="", columns=()):
        self.kind = kind
        self.text = text
        self.verb = verb
        self.table = table
        self.columns = tuple(columns)

    def summary(self):
        if self.verb == "UPDATE":
            return f"UPDATE {self.table} SET {', '.join(self.columns) or '?'}"
        if self.verb in ("DELETE", "INSERT", "REPLACE"):
            joiner = "FROM" if self.verb == "DELETE" else "INTO"
            return f"{self.verb} {joiner} {self.table}"
        if self.verb:
            return f"{self.verb} {self.table}".strip()
        return " ".join(self.text.split())[:80]


def _bare(name):
    return name.split(".")[-1].strip("\"`[]").lower()


def blank_literals(sql):
    return LITERAL_OR_COMMENT_RE.sub(lambda m: "''" if m.group(0).startswith("'") else " ", sql or "")


def classify_pragma(stmt):
    match = PRAGMA_RE.match(stmt)
    if not match:
        return UNKNOWN
    name, form = match.group(1).lower(), match.group(2)
    if name == "writable_schema":
        return WRITE
    if name in CONNECTION_PRAGMAS:
        return READ
    if form == "=":
        return WRITE
    if form == "(":
        if name in TABLE_ARG_PRAGMAS:
            return READ
        if name in QUERY_PRAGMAS or name in FILE_ACTION_PRAGMAS:
            return WRITE
        return UNKNOWN
    if name in QUERY_PRAGMAS or name in TABLE_ARG_PRAGMAS:
        return READ
    if name in FILE_ACTION_PRAGMAS:
        return WRITE
    return UNKNOWN


def describe_write(stmt):
    """(verb, table, columns) for a write statement, best effort."""
    update = UPDATE_RE.search(stmt)
    if update:
        return "UPDATE", _bare(update.group(1)), [c.lower() for c in SET_COLUMN_RE.findall(update.group(2))]
    delete = DELETE_RE.search(stmt)
    if delete:
        return "DELETE", _bare(delete.group(1)), []
    insert = INSERT_RE.search(stmt)
    if insert:
        return insert.group(1).upper(), _bare(insert.group(2)), []
    obj = OBJECT_RE.search(stmt)
    if obj:
        return obj.group(1).upper(), f"{obj.group(2).upper()} {_bare(obj.group(3))}", []
    words = WORD_RE.findall(stmt)
    return (words[0].upper() if words else "WRITE"), "", []


def classify_statement(stmt):
    words = WORD_RE.findall(stmt)
    head = words[0].upper() if words else ""
    if head == "WITH":
        if WITH_WRITE_RE.search(stmt):
            kind = WRITE
        else:
            kind = READ if re.search(r"\bSELECT\b", stmt, re.IGNORECASE) else UNKNOWN
    elif head == "PRAGMA":
        kind = classify_pragma(stmt)
    elif head in WRITE_HEADS:
        kind = WRITE
    elif head in READ_HEADS:
        kind = READ
    else:
        kind = UNKNOWN
    if kind == WRITE:
        verb, table, columns = describe_write(stmt)
        if head == "PRAGMA":
            verb, table = "PRAGMA", (PRAGMA_RE.match(stmt).group(1) if PRAGMA_RE.match(stmt) else "")
        return Statement(kind, stmt, verb, table, columns)
    return Statement(kind, stmt)


def classify_sql(sql):
    """Every statement in one SQL string, in order."""
    return [
        classify_statement(part.strip())
        for part in blank_literals(sql).split(";")
        if part.strip()
    ]


def classify_dot(line):
    name = line.strip()[1:].split(None, 1)[0].lower() if line.strip()[1:].split() else ""
    if name in READ_DOTS:
        return Statement(READ, line.strip())
    if name in WRITE_DOTS:
        return Statement(WRITE, line.strip(), "." + name, "")
    return Statement(UNKNOWN, line.strip())


def classify_cli_input(text):
    """Statements in sqlite3 shell input, where a line starting with `.` is a command."""
    out = []
    pending = []
    for line in (text or "").splitlines():
        so_far = "\n".join(pending).strip()
        if line.lstrip().startswith(".") and (not so_far or so_far.endswith(";")):
            out.extend(classify_sql(so_far))
            pending = []
            out.append(classify_dot(line))
            continue
        pending.append(line)
    out.extend(classify_sql("\n".join(pending)))
    return out


def looks_like_sql(text):
    words = WORD_RE.findall(blank_literals(text))
    return bool(words) and (words[0].upper() in WRITE_HEADS | READ_HEADS | {"PRAGMA", "WITH"})
