"""invoker-db-guard: a direct write to Invoker's live SQLite database is blocked,
and the block names the invoker-cli command that does the same job.

Invoker's own CLAUDE.md says to use the headless command before any direct
SQLite command, and to stop and plan a new headless command when none
exists. That rule is prose and loses to convenience; this is the mechanical
half.

Three outcomes, not two. `hit`: the command writes to Invoker's database.
`clean`: it provably does not -- the path is not Invoker's, or every
statement is on the read list, or the connection is opened read-only.
`unchecked`: it reaches Invoker's database but the guard cannot see what it
does (SQL from a file, a program kept in a script, a path it cannot
resolve). `hit` and `unchecked` both block, with different messages.
"""
from __future__ import annotations

import os
import re

from programs import Verdict, classify_program_text, classify_python, db_path, mentioned_path
from shell import ASSIGN_RE, default_env, parse_stages
from statements import UNKNOWN, WRITE, classify_cli_input

HIT = "hit"
CLEAN = "clean"
UNCHECKED = "unchecked"

SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
NODES = {"node", "nodejs", "bun"}
PYTHON_RE = re.compile(r"^(?:python(?:\d+(?:\.\d+)*)?|pypy3?)$")
WRAPPERS = {
    "sudo", "env", "timeout", "nice", "nohup", "time", "command", "exec",
    "builtin", "stdbuf", "xargs", "then", "do", "else", "elif", "if", "while",
    "until", "!", "{",
}
WRAPPER_ARG_FLAGS = {
    "sudo": {"-u", "-g", "-C", "-D", "-h", "-p", "-U", "-r", "-t"},
    "timeout": {"-s", "-k", "--signal", "--kill-after"},
    "nice": {"-n"},
    "xargs": {"-I", "-n", "-P", "-L", "-s", "-d", "-E", "-a"},
    "env": {"-u", "-C", "-S"},
}
SQLITE_ONE_ARG = {"-cmd", "-init", "-separator", "-newline", "-nullvalue", "-mmap", "-vfs", "-maxsize", "-escape"}
SQLITE_TWO_ARG = {"-lookaside", "-pagecache", "-heap"}
PYTHON_ARG_FLAGS = {"-W", "-X", "-Q"}
NODE_ARG_FLAGS = {"-r", "--require", "--import", "--loader", "--input-type", "-C", "--conditions"}
FILE_WRITE_ANY = {"rm", "unlink", "shred", "truncate", "mv"}
FILE_WRITE_DEST = {"cp", "install", "rsync", "ln"}
WRITE_REDIRECTS = {">", ">>", ">|", "&>", "&>>", "<>"}
MAX_DEPTH = 4

SET_FIELDS = {
    "execution_agent": "agent",
    "pool_id": "pool",
    "pool_member_id": "pool",
    "runner_kind": "executor",
    "remote_target_id": "executor",
}
SET_COMMANDS = {
    "agent": "invoker-cli set agent <taskId> <agent>",
    "pool": "invoker-cli set pool <taskId> <pool>",
    "executor": "invoker-cli set executor <taskId> <executor>",
}
STATUS_COMMANDS = (
    "invoker-cli retry-task <taskId>     one task",
    "invoker-cli retry <workflowId>      rerun failed tasks, keep completed ones",
    "invoker-cli resume <workflowId>     pick an incomplete workflow back up",
)
SET_LANDING = (
    "`invoker-cli set` is landing, not shipped: Invoker's headless registry has "
    "`set` for these task fields and the UI reaches it over REST, but the CLI "
    "does not expose it yet. Until it lands, make this change in the Invoker UI "
    "or ask the user -- not in SQL."
)
NO_COMMAND = (
    "No headless command covers {what}. Per Invoker's CLAUDE.md, stop here: the "
    "next step is adding that headless command, so give the user a concrete plan "
    "for it instead of writing SQL. If the user approves a one-off write anyway, "
    "hand them a script to run themselves."
)
READ_ONLY_HINT = (
    "It opens the database read-write. To only read, open it read-only -- "
    "`sqlite3 -readonly`, or sqlite3.connect('file:<path>?mode=ro', uri=True) -- "
    "or use `invoker-cli query tasks` / `invoker-cli query workflows`."
)
UNCHECKED_MESSAGE = (
    "invoker-db-guard: could not tell whether this command writes to Invoker's "
    "live database ({path}): {why}. A guard that cannot check does not assume "
    "safe, so it is blocked. Make it checkable: put the SQL inline in the "
    "command, open the database read-only (`sqlite3 -readonly`, or "
    "sqlite3.connect('file:<path>?mode=ro', uri=True)), or read through "
    "`invoker-cli query tasks` / `invoker-cli query workflows`."
)


def command_words(words):
    """The words of the command a stage really runs, past assignments and wrappers."""
    k = 0
    while k < len(words):
        word = words[k]
        if ASSIGN_RE.match(word):
            k += 1
            continue
        base = os.path.basename(word)
        if base in WRAPPERS:
            k += 1
            arg_flags = WRAPPER_ARG_FLAGS.get(base, set())
            while k < len(words) and (words[k].startswith("-") or ASSIGN_RE.match(words[k])):
                k += 2 if words[k] in arg_flags else 1
            if base == "timeout" and k < len(words):
                k += 1
            continue
        if base == "uv" and words[k + 1:k + 2] == ["run"]:
            k += 2
            while k < len(words) and words[k].startswith("-"):
                k += 1
            continue
        return words[k:]
    return []


def stdin_of(stage):
    """(visible stdin texts, whether stdin also comes from somewhere unseen)."""
    texts = list(stage.stdin_texts)
    hidden = any(op in ("<", "<&") for op, _ in stage.redirects)
    source = stage.piped_from
    if source is not None:
        words = command_words(source.words)
        head = os.path.basename(words[0]) if words else ""
        if head == "echo":
            texts.append(" ".join(w for w in words[1:] if w not in ("-n", "-e", "-E")))
        elif head == "printf":
            texts.append(" ".join(words[1:]))
        elif head == "cat" and len(words) == 1 and source.stdin_texts:
            texts.extend(source.stdin_texts)
        else:
            hidden = True
    return texts, hidden


def unresolved(word):
    return "$" in (word or "")


def analyze_sqlite_cli(args, stage, python_module=False):
    read_only = False
    hidden = ""
    filename = None
    positional = []
    cmd_sql = []
    k = 0
    while k < len(args):
        arg = args[k]
        if arg.startswith("-") and len(arg) > 1 and not python_module:
            flag = "-" + arg.lstrip("-")
            if flag == "-readonly":
                read_only = True
            elif flag == "-cmd":
                cmd_sql.append(args[k + 1] if k + 1 < len(args) else "")
                k += 1
            elif flag == "-init":
                hidden = f"its SQL comes from the -init file {args[k + 1] if k + 1 < len(args) else ''}".strip()
                k += 1
            elif flag in SQLITE_TWO_ARG:
                k += 2
            elif flag in SQLITE_ONE_ARG:
                k += 1
            elif flag in ("-A", "-archive"):
                hidden = "it runs in archive mode"
                break
            k += 1
            continue
        if filename is None:
            filename = arg
        else:
            positional.append(arg)
        k += 1
    texts = cmd_sql + positional
    if not positional:
        stdin_texts, stdin_hidden = stdin_of(stage)
        texts += stdin_texts
        redirect = next((target for op, target in stage.redirects if op in ("<", "<&")), None)
        if redirect:
            hidden = hidden or f"its SQL comes from the file redirect `< {redirect}`, which the guard does not open"
        elif stdin_hidden:
            hidden = hidden or "its SQL is piped in from a command the guard cannot read"
        elif not stdin_texts:
            hidden = hidden or "no SQL is given, so it would read statements from stdin"
    statements = [s for text in texts for s in classify_cli_input(text)]
    if any(s.kind == UNKNOWN and s.text.startswith(".read") for s in statements):
        hidden = hidden or "its SQL comes from a `.read` file"
    path = db_path(filename) or next((mentioned_path(t) for t in texts if mentioned_path(t)), None)
    if filename and re.search(r"[?&](mode=ro|immutable=1)\b", filename):
        read_only = True
    writes = [s for s in statements if s.kind == WRITE]
    if path is None:
        if writes and unresolved(filename):
            return Verdict(UNCHECKED, filename, why=f"the database path {filename} is not set in this command, so it may be Invoker's")
        return None
    if writes:
        return Verdict(HIT, path, writes)
    if read_only:
        return Verdict(CLEAN, path)
    unknown = [s for s in statements if s.kind == UNKNOWN]
    if hidden:
        return Verdict(UNCHECKED, path, why=hidden)
    if unknown:
        return Verdict(UNCHECKED, path, why=f"`{unknown[0].text[:60]}` is not a statement the guard can vouch for as read-only")
    return Verdict(CLEAN, path)


def any_mention(words):
    return next((db_path(w) or mentioned_path(w) for w in words if db_path(w) or mentioned_path(w)), None)


def program_source(args, arg_flags, eval_flags):
    """(program text or None, script path or None, remaining args, reads stdin)."""
    k = 0
    while k < len(args):
        arg = args[k]
        if arg in eval_flags:
            return (args[k + 1] if k + 1 < len(args) else ""), None, args[k + 2:], False
        for flag in eval_flags:
            if flag.startswith("--") and arg.startswith(flag + "="):
                return arg[len(flag) + 1:], None, args[k + 1:], False
        if arg == "-m":
            return None, (args[k + 1] if k + 1 < len(args) else "-m"), args[k + 2:], False
        if arg == "-":
            return None, None, args[k + 1:], True
        if arg.startswith("-"):
            k += 2 if arg in arg_flags else 1
            continue
        return None, arg, args[k + 1:], False
    return None, None, [], True


def analyze_program(args, stage, language):
    if language == "python":
        program, script, rest, from_stdin = program_source(args, PYTHON_ARG_FLAGS, {"-c"})
    else:
        program, script, rest, from_stdin = program_source(args, NODE_ARG_FLAGS, {"-e", "--eval", "-p", "--print"})
    mention = any_mention(rest)
    if from_stdin:
        texts, hidden = stdin_of(stage)
        if texts:
            program = "\n".join(texts)
        elif mention:
            return Verdict(UNCHECKED, mention, why="the program is fed on stdin from somewhere the guard cannot read")
        else:
            return None
    if program is None:
        if mention:
            return Verdict(UNCHECKED, mention, why=f"its code is in {script}, which the guard does not open")
        return None
    if language == "python":
        return classify_python(program, mention)
    return classify_program_text(program, mention)


def analyze_file_op(head, args):
    operands = [a for a in args if not a.startswith("-")]
    if head == "dd":
        hits = [a[3:] for a in args if a.startswith("of=") and db_path(a[3:])]
    elif head in FILE_WRITE_ANY:
        hits = [a for a in operands if db_path(a)]
    else:
        hits = [operands[-1]] if len(operands) >= 2 and db_path(operands[-1]) else []
    if not hits:
        return None
    return Verdict(HIT, hits[0], file_op=f"a file-level `{head}` of {hits[0]}")


def analyze_redirects(stage):
    for op, target in stage.redirects:
        if op in WRITE_REDIRECTS and db_path(target):
            return Verdict(HIT, target, file_op=f"a shell redirect `{op} {target}`")
    return None


def shell_inline(args):
    for k, arg in enumerate(args):
        if arg.startswith("-") and not arg.startswith("--") and "c" in arg[1:]:
            return args[k + 1] if k + 1 < len(args) else ""
        if not arg.startswith("-"):
            return None
    return None


def analyze_stage(stage, env, depth):
    verdicts = [analyze_redirects(stage)]
    words = command_words(stage.words)
    if not words:
        return [v for v in verdicts if v]
    head = os.path.basename(words[0])
    args = words[1:]
    if head in SHELLS:
        inline = shell_inline(args)
        if inline is not None:
            verdicts.extend(analyze(inline, env, depth + 1))
        elif all(a.startswith("-") for a in args):
            for body in stdin_of(stage)[0]:
                verdicts.extend(analyze(body, env, depth + 1))
    elif head == "eval":
        verdicts.extend(analyze(" ".join(args), env, depth + 1))
    elif head == "sqlite3":
        verdicts.append(analyze_sqlite_cli(args, stage))
    elif PYTHON_RE.match(head):
        if args[:2] == ["-m", "sqlite3"]:
            verdicts.append(analyze_sqlite_cli(args[2:], stage, python_module=True))
        else:
            verdicts.append(analyze_program(args, stage, "python"))
    elif head in NODES:
        verdicts.append(analyze_program(args, stage, "node"))
    elif head in FILE_WRITE_ANY or head in FILE_WRITE_DEST or head == "dd":
        verdicts.append(analyze_file_op(head, args))
    return [v for v in verdicts if v]


def analyze(command, env, depth=0):
    """Every verdict for a command string; stages are all checked, none short-circuit."""
    if depth > MAX_DEPTH:
        return []
    verdicts = []
    for stage in parse_stages(command, env):
        verdicts.extend(analyze_stage(stage, env, depth))
    return verdicts


def classify(command, env=None):
    """(outcome, verdicts) for one Bash command string."""
    verdicts = analyze(command or "", dict(env) if env is not None else default_env())
    if any(v.outcome == HIT for v in verdicts):
        return HIT, verdicts
    if any(v.outcome == UNCHECKED for v in verdicts):
        return UNCHECKED, verdicts
    return CLEAN, verdicts


def plan(verdicts):
    """(what the command does, the replacement lines) for the hit verdicts."""
    did, lines, uncovered = [], [], []
    status = delete = read_write = False
    kinds = []
    for verdict in verdicts:
        if verdict.outcome != HIT:
            continue
        if verdict.file_op:
            did.append(verdict.file_op)
            uncovered.append(verdict.file_op)
        if verdict.read_write_open:
            did.append("opens it read-write")
            read_write = True
        for write in verdict.writes:
            did.append(write.summary())
            covered = False
            if write.verb == "UPDATE" and write.table == "tasks":
                if "status" in write.columns:
                    status = covered = True
                for column in write.columns:
                    if column in SET_FIELDS:
                        kinds.append(SET_FIELDS[column])
                        covered = True
                if "config" in write.columns and verdict.config_kinds:
                    kinds.extend(verdict.config_kinds)
                    covered = True
            elif write.verb == "DELETE" and write.table == "workflows":
                delete = covered = True
            if not covered:
                uncovered.append(write.summary())
    if status:
        lines.append("tasks.status -> use one of:")
        lines.extend("  " + c for c in STATUS_COMMANDS)
    if delete:
        lines.append("deleting a workflow -> invoker-cli delete <workflowId>")
    seen = []
    for kind in kinds:
        if kind not in seen:
            seen.append(kind)
    fields = {kind: sorted(col for col, k in SET_FIELDS.items() if k == kind) for kind in seen}
    for kind in seen:
        lines.append(f"tasks.{' / '.join(fields[kind])} -> {SET_COMMANDS[kind]}   (landing)")
    if seen:
        lines.append(SET_LANDING)
    if uncovered:
        lines.append(NO_COMMAND.format(what="; ".join(dict.fromkeys(uncovered))))
    if read_write and not lines:
        lines.append(READ_ONLY_HINT)
    return list(dict.fromkeys(did)), lines


def block_message(outcome, verdicts):
    if outcome == HIT:
        hits = [v for v in verdicts if v.outcome == HIT]
        did, lines = plan(hits)
        body = "\n".join(lines)
        return (
            f"invoker-db-guard: blocked a direct write to Invoker's live database ({hits[0].path}).\n"
            f"What it does: {'; '.join(did)}.\n"
            "Invoker's CLAUDE.md: use the headless command, not SQL.\n"
            f"{body}\n"
            "Check the result with `invoker-cli query tasks --workflow <workflowId>`, not SQLite."
        )
    first = next(v for v in verdicts if v.outcome == UNCHECKED)
    return UNCHECKED_MESSAGE.format(path=first.path, why=first.why)


def decide(payload, env=None):
    """Blocking feedback for a PreToolUse Bash call, or None to allow it."""
    tool_input = payload.get("tool_input") or {}
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not command:
        return None
    outcome, verdicts = classify(command, env)
    if outcome == CLEAN:
        return None
    return block_message(outcome, verdicts)

