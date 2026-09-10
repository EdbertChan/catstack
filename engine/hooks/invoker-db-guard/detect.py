"""invoker-db-guard: the owner owns the write, so SQL that goes around it is lost work.

Invoker keeps all state in one WAL-mode SQLite file and enforces a
single-writer owner: one process holds the writer lock and its in-memory
state is authoritative. A row changed underneath that process is not
observed by it and is overwritten by the next thing the owner flushes. The
correct edit therefore always goes through the owner, which is what the
headless commands do.

Invoker's own always-loaded prose already says to reach for the headless
command first and, when none exists, to stop and propose adding one. Prose
that competes with convenience loses; a PreToolUse hook does not. Leveson,
*Engineering a Safer World* (MIT Press, 2011), states the general form: a
constraint that is only written down is not a control, because nothing in
the loop enforces it.

Three detectors, one target resolver.

1. WRITABLE PYTHON CONNECT (`writable_connect`). `sqlite3.connect(<the live
   db>)`, or the same call through whatever alias `import sqlite3 as <name>`
   bound, without a `file:...?mode=ro` URI plus `uri=True` opens the file
   read-write, takes locks against the owner, and can create or recover a
   WAL. That is true even when every statement that follows is a SELECT, so
   the open itself is the defect and the read-only spelling is the fix.

2. MUTATING SQLITE CLI (`mutating_cli`). `sqlite3 <the live db> "UPDATE ..."`
   and its INSERT / DELETE / REPLACE / DROP / ALTER / CREATE / `PRAGMA
   writable_schema` siblings, including a heredoc body fed to the same
   invocation. The database is found by scanning every argument rather than
   by counting position, so a flag carrying its own value (`-cmd "UPDATE ..."
   <db>`) cannot push the path out of the slot it was expected in.

3. UNRESOLVED TARGET (`unresolved_target`). A sqlite entry point in a command
   that mentions Invoker, whose database path or whose SQL text cannot be
   read out of the command string -- an unbound `$DB`, a path built by a
   call, SQL redirected in from a file. This is the third outcome. Saltzer
   and Schroeder's fail-safe-defaults principle puts the burden on the
   command to show it is safe rather than on the guard to show it is not, so
   an entry point that cannot be classified is reported as unchecked and
   blocked, never returned as clean.

The block message names the headless command that owns the state the SQL
touches, chosen from the columns the statement actually assigns. When no
command owns it, the message says so and names adding one as the next step,
because "use the CLI" with no command in it is the advice that already lost.

KNOWN FALSE POSITIVE: scoping is per command string, not per statement. One
command that opens the live database read-only and, separately, runs an
UPDATE against some other database is blocked on the pair. Split it into two
commands. A mutating verb sitting inside a quoted SQL string literal
(`where name = 'delete'`) is also read as a statement.

FAIL DIRECTION: two reads, resolving opposite ways on purpose. An entry
point that cannot be classified fails closed (blocked, named as unchecked),
because the file it might be touching is the live one. Everything else fails
open: an unparseable payload, a missing command, and any unexpected
exception in the detector allow the call, so a detector bug can only
under-block.
"""
from __future__ import annotations

import json
import re
import shlex

DB_PATH_RE = re.compile(r"(?:[\w./~${}-]*/)?invoker\.db(?:-wal|-shm)?(?![\w.-])")

INVOKER_MENTION_RE = re.compile(r"invoker", re.IGNORECASE)

ASSIGN_RE = re.compile(
    r"""(?:^|[\s;&|(])(?:export\s+)?([A-Za-z_]\w*)\s*=\s*"""
    r"""(?:"([^"\n]*)"|'([^'\n]*)'|([^\s;&|)"'\n]+))""",
    re.MULTILINE,
)

VAR_REF_RE = re.compile(r"\$\{(\w+)\}|\$(\w+)|\{(\w+)\}")

STRING_LITERAL_RE = re.compile(r"""^[rbufRBUF]{0,2}(?:\"\"\"|'''|"|')""")

HOME_ALIAS = {"HOME": "~"}

CONNECT_RE = re.compile(r"sqlite3\s*\.\s*connect\s*\(")

CLI_RE = re.compile(
    r"""(?:^|[\n;()`"']|\|\||&&|\||&|\$\()\s*"""
    r"(?:sudo\s+|nohup\s+|timeout\s+[\d.]+[smhd]?\s+|env\s+\w+=\S+\s+)*"
    r"sqlite3(?=\s|$)"
)

SQLITE3_IMPORT_RE = re.compile(r"\bimport\s+sqlite3(?:\s+as\s+(\w+))?")

ALIASED_CONNECT_RE = re.compile(r"\b(\w+)\s*\.\s*connect\s*\(")

HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_]\w*)\1")

MUTATING_SQL_RE = re.compile(
    r"""(?:^|[;\n"'`]|\bbegin\b|\bthen\b|\bdo\b)\s*"""
    r"(update|insert|delete|replace|drop|alter|create|pragma\s+writable_schema)\b",
    re.IGNORECASE | re.MULTILINE,
)

UPDATE_SET_RE = re.compile(
    r"""update\s+(?:or\s+\w+\s+)?["'`\[]?(\w+)["'`\]]?\s+set\s+"""
    r"""(.*?)(?=\bwhere\b|\breturning\b|["'`]{3}|$)""",
    re.IGNORECASE | re.DOTALL,
)

INSERT_COLUMNS_RE = re.compile(
    r"""insert\s+(?:or\s+\w+\s+)?into\s+["'`\[]?(\w+)["'`\]]?\s*\(([^)]*)\)""",
    re.IGNORECASE | re.DOTALL,
)

COLUMN_ASSIGN_RE = re.compile(r"""(?:^|,)\s*["'`\[]?(\w+)["'`\]]?\s*=""")

DELETE_FROM_RE = re.compile(r"""delete\s+from\s+["'`\[]?(\w+)""", re.IGNORECASE)

DROP_TABLE_RE = re.compile(r"""drop\s+table\s+(?:if\s+exists\s+)?["'`\[]?(\w+)""", re.IGNORECASE)

OPAQUE_SQL_RE = re.compile(r"""^(?:\$\(|`)|^\.read\b|^--?init\b""")

ROUTING_COLUMNS = frozenset(
    {"execution_agent", "pool_id", "runner_kind", "pool_member_id", "remote_target_id"}
)
STATUS_COLUMNS = frozenset({"status"})
WORKFLOW_TABLES = frozenset({"workflows", "tasks"})

SHELL_LIKE_TOOL_NAMES = frozenset(
    {
        "Bash", "bash", "shell", "Shell", "exec", "exec_command",
        "run_terminal_cmd", "local_shell", "run_command", "shell_call",
    }
)

READ_ONLY_SPELLING = (
    'sqlite3.connect("file:<path>?mode=ro", uri=True)   (python)\n'
    "  sqlite3 -readonly <path> \"select ...\"                (cli)\n"
    "  invoker-cli query tasks --workflow <id> --output json   (through the owner)"
)

OWNER_SENTENCE = (
    "The owner process holds the writer lock and its in-memory state is "
    "authoritative -- a row changed underneath it is never observed and is "
    "overwritten by the owner's next flush."
)

ROUTE_TASK_COMMAND = (
    "invoker-cli route-task <taskId> [--agent <agent>|--pool <poolId>|"
    "--runner <kind>|--clear-member]\n"
    "    This one is landing, not shipped. If it is not on your Invoker yet, "
    "adding it is the task -- not writing the UPDATE."
)

STATUS_COMMAND = (
    "invoker-cli retry-task <taskId>     one task again\n"
    "    invoker-cli retry <workflowId>      the whole workflow again\n"
    "    invoker-cli resume <workflowId>     pick it up where it stopped"
)

DELETE_COMMAND = "invoker-cli delete <workflowId>"

UNCOVERED_TEMPLATE = (
    "no headless command covers {what}. Per Invoker's CLAUDE.md the next step "
    "is to add one: stop and put a concrete plan for that command in front of "
    "the user. Writing the SQL yourself is the thing that rule forbids."
)


def _strip_quotes(text: str) -> str:
    text = text.strip()
    for prefix in ("f", "rf", "fr", "b", "r", "u", "F", "R", "B", "U"):
        if text.lower().startswith(prefix) and len(text) > len(prefix) and text[len(prefix)] in "\"'":
            text = text[len(prefix):]
            break
    for quote in ('"""', "'''", '"', "'"):
        if text.startswith(quote) and text.endswith(quote) and len(text) >= 2 * len(quote):
            return text[len(quote):-len(quote)]
    return text


def shell_and_python_bindings(command: str) -> dict[str, str]:
    """Every NAME=value and NAME = "value" the command binds to itself.

    Shell assignments and python assignments have the same shape here, and a
    database path can arrive through either -- `DB=/x/invoker.db` then
    `"$DB"`, or `db = "/x/invoker.db"` then `connect(db)`.
    """
    bindings: dict[str, str] = dict(HOME_ALIAS)
    for match in ASSIGN_RE.finditer(command):
        name = match.group(1)
        value = next((g for g in match.groups()[1:] if g is not None), "")
        bindings[name] = value
    return bindings


def expand(text: str, bindings: dict[str, str]) -> str:
    def substitute(match: re.Match[str]) -> str:
        name = match.group(1) or match.group(2) or match.group(3)
        return bindings.get(name, match.group(0))

    previous = None
    current = text
    for _ in range(4):
        if current == previous:
            break
        previous = current
        current = VAR_REF_RE.sub(substitute, current)
    return current


def _unresolved_refs(text: str, bindings: dict[str, str]) -> list[str]:
    names = []
    for match in VAR_REF_RE.finditer(text):
        name = match.group(1) or match.group(2) or match.group(3)
        if name not in bindings:
            names.append(name)
    return names


def targets_invoker_db(text: str) -> bool:
    return bool(DB_PATH_RE.search(text))


def _balanced_args(command: str, open_paren_index: int) -> str | None:
    depth = 0
    quote: str | None = None
    for index in range(open_paren_index, len(command)):
        char = command[index]
        if quote:
            if char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return command[open_paren_index + 1:index]
    return None


def _split_top_level(text: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    quote: str | None = None
    current: list[str] = []
    for char in text:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
            current.append(char)
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


def _segment_from(command: str, start: int) -> str:
    quote: str | None = None
    for index in range(start, len(command)):
        char = command[index]
        if quote:
            if char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
            continue
        if char in ";\n|&":
            return command[start:index]
    return command[start:]


def heredoc_bodies(command: str) -> dict[str, str]:
    bodies: dict[str, str] = {}
    for match in HEREDOC_RE.finditer(command):
        tag = match.group(2)
        closer = re.compile(rf"^\s*{re.escape(tag)}\s*$", re.MULTILINE)
        after = closer.search(command, match.end())
        if after:
            bodies[tag] = command[match.end():after.start()]
    return bodies


def _connect_sites(command: str) -> list[re.Match[str]]:
    """sqlite3.connect(, plus <alias>.connect( when sqlite3 is imported as one.

    `import sqlite3 as s` then `s.connect(path)` is the same open through a
    different name, so the alias the command binds is resolved rather than
    the module name being assumed.
    """
    sites = list(CONNECT_RE.finditer(command))
    aliases = {alias for alias in SQLITE3_IMPORT_RE.findall(command) if alias}
    if not aliases:
        return sites
    seen = {match.end() for match in sites}
    for match in ALIASED_CONNECT_RE.finditer(command):
        if match.group(1) in aliases and match.end() not in seen:
            sites.append(match)
    return sorted(sites, key=lambda m: m.start())


def python_connects(command: str, bindings: dict[str, str]) -> list[dict]:
    """Every sqlite3.connect() in the command, with its path resolved."""
    found: list[dict] = []
    for match in _connect_sites(command):
        args_text = _balanced_args(command, match.end() - 1)
        if args_text is None:
            found.append({"path": "", "resolved": False, "read_only": False, "raw": ""})
            continue
        args = _split_top_level(args_text)
        if not args:
            found.append({"path": "", "resolved": False, "read_only": False, "raw": args_text})
            continue
        raw_path = args[0]
        kwargs_text = ",".join(args[1:])
        if STRING_LITERAL_RE.match(raw_path):
            literal = _strip_quotes(raw_path)
        elif re.fullmatch(r"[A-Za-z_]\w*", raw_path) and raw_path in bindings:
            literal = bindings[raw_path]
        else:
            found.append({"path": raw_path, "resolved": False, "read_only": False, "raw": raw_path})
            continue
        expanded = expand(literal, bindings)
        if _unresolved_refs(expanded, bindings):
            found.append({"path": expanded, "resolved": False, "read_only": False, "raw": raw_path})
            continue
        uri_true = re.search(r"\buri\s*=\s*True\b", kwargs_text) is not None
        read_only = uri_true and re.search(r"[?&]mode=ro\b", expanded) is not None
        found.append({"path": expanded, "resolved": True, "read_only": read_only, "raw": raw_path})
    return found


def cli_invocations(command: str, bindings: dict[str, str]) -> list[dict]:
    """Every `sqlite3` shell invocation, with its db path and SQL text."""
    bodies = heredoc_bodies(command)
    found: list[dict] = []
    for match in CLI_RE.finditer(command):
        segment = _segment_from(command, match.end())
        try:
            tokens = shlex.split(segment, posix=True)
        except ValueError:
            found.append({"path": "", "resolved": False, "sql": "", "sql_known": False, "read_only": False})
            continue
        read_only = any(t in ("-readonly", "--readonly") for t in tokens)
        expanded = [expand(t, bindings) for t in tokens]
        db_index = next(
            (i for i, token in enumerate(expanded) if targets_invoker_db(token)), None
        )
        if db_index is None:
            db_index = next((i for i, t in enumerate(tokens) if not t.startswith("-")), None)
        if db_index is None:
            found.append({"path": "", "resolved": False, "sql": "", "sql_known": False, "read_only": read_only})
            continue
        resolved_path = expanded[db_index]
        path_resolved = not _unresolved_refs(resolved_path, bindings)
        sql_tokens = [t for i, t in enumerate(expanded) if i != db_index and not t.startswith("-")]
        sql_text = " ".join(sql_tokens)
        sql_known = bool(sql_tokens)
        heredoc = HEREDOC_RE.search(segment)
        if heredoc:
            sql_text += "\n" + bodies.get(heredoc.group(2), "")
            sql_known = heredoc.group(2) in bodies
        elif re.search(r"(?<![0-9<])<(?!<)", segment) or OPAQUE_SQL_RE.search(sql_text):
            sql_known = False
        if _unresolved_refs(sql_text, bindings):
            sql_known = False
        found.append({
            "path": resolved_path,
            "resolved": path_resolved,
            "sql": expand(sql_text, bindings),
            "sql_known": sql_known,
            "read_only": read_only,
        })
    return found


def assigned_columns(sql: str) -> set[str]:
    columns: set[str] = set()
    for _table, set_clause in UPDATE_SET_RE.findall(sql):
        columns.update(name.lower() for name in COLUMN_ASSIGN_RE.findall(set_clause))
    for _table, column_list in INSERT_COLUMNS_RE.findall(sql):
        columns.update(name.strip().strip("\"'`[]").lower() for name in column_list.split(","))
    return {c for c in columns if c}


def deleted_tables(sql: str) -> set[str]:
    return {t.lower() for t in DELETE_FROM_RE.findall(sql)} | {
        t.lower() for t in DROP_TABLE_RE.findall(sql)
    }


def is_mutating(sql: str) -> bool:
    return MUTATING_SQL_RE.search(sql) is not None


def headless_commands(sql: str) -> list[str]:
    """Map what the SQL touches onto the command that owns that state."""
    columns = assigned_columns(sql)
    tables = deleted_tables(sql)
    lines: list[str] = []
    if columns & ROUTING_COLUMNS:
        touched = ", ".join(f"tasks.{c}" for c in sorted(columns & ROUTING_COLUMNS))
        lines.append(f"  {touched}\n    {ROUTE_TASK_COMMAND}")
    if columns & STATUS_COLUMNS:
        lines.append(f"  tasks.status\n    {STATUS_COMMAND}")
    if tables & WORKFLOW_TABLES:
        touched = ", ".join(sorted(tables & WORKFLOW_TABLES))
        lines.append(f"  deleting rows from {touched}\n    {DELETE_COMMAND}")
    leftover = columns - ROUTING_COLUMNS - STATUS_COLUMNS
    if leftover:
        touched = ", ".join(f"tasks.{c}" for c in sorted(leftover))
        lines.append("  " + UNCOVERED_TEMPLATE.format(what=touched))
    if not lines and is_mutating(sql):
        lines.append("  " + UNCOVERED_TEMPLATE.format(what="this statement"))
    return lines


def _write_message(path: str, shape: str, sql: str) -> str:
    body = [
        "invoker-db-guard: this writes to Invoker's live database directly.",
        f"  target: {path or '(this command)'}",
        f"  shape:  {shape}",
        "",
        "Use the headless command that owns this state:",
    ]
    body.extend(headless_commands(sql))
    body.extend(["", OWNER_SENTENCE, "", "To read instead, open read-only:", "  " + READ_ONLY_SPELLING])
    return "\n".join(body)


def _read_only_open_message(path: str) -> str:
    return "\n".join([
        "invoker-db-guard: this opens Invoker's live database read-write.",
        f"  target: {path}",
        "  shape:  sqlite3.connect() with no file:...?mode=ro URI and no uri=True",
        "",
        "Every statement here is a read, but the open itself takes writer locks "
        "against the owner and can recover or create a WAL.",
        "",
        OWNER_SENTENCE,
        "",
        "Open it read-only, or read through the owner:",
        "  " + READ_ONLY_SPELLING,
    ])


def _unchecked_message(reason: str, detail: str) -> str:
    return "\n".join([
        "invoker-db-guard: UNCHECKED -- this command reaches SQLite and the guard "
        "could not classify it.",
        f"  reason: {reason}",
        f"  detail: {detail}",
        "",
        "A check that could not run is not a pass, so this is blocked rather than "
        "allowed. Put the database path and the SQL literally in the command so "
        "the guard can read them, or use the headless surface:",
        "  invoker-cli query tasks|workflows --output json     read",
        "  invoker-cli retry-task|retry|resume|delete          write",
        "",
        OWNER_SENTENCE,
    ])


def problems(command: str) -> tuple[str, list[str]]:
    """Return (outcome, messages) where outcome is hit, clean or unchecked."""
    if not command.strip():
        return "clean", []

    bindings = shell_and_python_bindings(command)
    connects = python_connects(command, bindings)
    invocations = cli_invocations(command, bindings)
    if not connects and not invocations:
        return "clean", []

    mentions_invoker = INVOKER_MENTION_RE.search(command) is not None
    whole_command_sql = command
    hits: list[str] = []
    unchecked: list[str] = []

    for connect in connects:
        if not connect["resolved"]:
            if mentions_invoker:
                unchecked.append(_unchecked_message(
                    "sqlite3.connect() path could not be resolved from this command",
                    f"connect argument: {connect['raw'] or '(unreadable)'}",
                ))
            continue
        if not targets_invoker_db(connect["path"]):
            continue
        if connect["read_only"]:
            if is_mutating(whole_command_sql):
                hits.append(_write_message(
                    connect["path"],
                    "sqlite3.connect() with mode=ro, but a mutating statement is executed on it",
                    whole_command_sql,
                ))
            continue
        if is_mutating(whole_command_sql):
            hits.append(_write_message(
                connect["path"],
                "python sqlite3.connect() opened read-write (no mode=ro URI, no uri=True)",
                whole_command_sql,
            ))
        else:
            hits.append(_read_only_open_message(connect["path"]))

    for invocation in invocations:
        if not invocation["resolved"]:
            if mentions_invoker:
                unchecked.append(_unchecked_message(
                    "the sqlite3 database argument could not be resolved from this command",
                    f"database argument: {invocation['path'] or '(none given)'}",
                ))
            continue
        if not targets_invoker_db(invocation["path"]):
            continue
        if not invocation["sql_known"]:
            unchecked.append(_unchecked_message(
                "sqlite3 targets Invoker's database but its SQL is not in this command",
                f"database argument: {invocation['path']}",
            ))
            continue
        if invocation["read_only"] and not is_mutating(invocation["sql"]):
            continue
        if is_mutating(invocation["sql"]):
            hits.append(_write_message(
                invocation["path"],
                "sqlite3 cli running a mutating statement",
                invocation["sql"],
            ))

    if hits:
        return "hit", _dedupe(hits)
    if unchecked:
        return "unchecked", _dedupe(unchecked)
    return "clean", []


def _dedupe(messages: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for message in messages:
        if message not in seen:
            seen.add(message)
            ordered.append(message)
    return ordered


def tool_name(payload: dict) -> str:
    return str(
        payload.get("tool_name")
        or payload.get("toolName")
        or payload.get("tool")
        or payload.get("name")
        or ""
    )


def command_text(payload: dict) -> str:
    tool_input = payload.get("tool_input") or payload.get("toolInput") or payload.get("input") or {}
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except (json.JSONDecodeError, TypeError):
            return tool_input
    if not isinstance(tool_input, dict):
        return ""
    return str(tool_input.get("command") or tool_input.get("cmd") or "")


def pretooluse_outcome(raw: str) -> tuple[str, list[str]]:
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return "clean", []
    if not isinstance(payload, dict):
        return "clean", []
    if tool_name(payload) not in SHELL_LIKE_TOOL_NAMES:
        return "clean", []
    return problems(command_text(payload))
