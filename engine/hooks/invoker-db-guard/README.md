# invoker-db-guard

PreToolUse hook on the **Bash** tool: refuses a command that writes to
Invoker's live SQLite database, and names the headless command that owns the
same state. Exits 2 with the message on stderr.

Invoker keeps everything in one WAL-mode SQLite file and enforces a
single-writer owner. One process holds the writer lock and its in-memory
state is authoritative, so a row changed underneath it is never observed and
is overwritten by the owner's next flush. The SQL appears to work, prints
its row count, and changes nothing the owner will act on. That is why the
answer is always a command and never a better UPDATE.

Invoker's own always-loaded prose already says to reach for the headless
command first, and to stop and propose adding one when none exists. This hook
exists because that prose is a written constraint with nothing in the loop
enforcing it — the property it asserts is not checkable at the moment the
command is about to run, so it loses to convenience exactly when it matters.

## Fires on

A Bash command that both **targets** Invoker's database and **is not
read-only**.

**Target** — any of these spellings, resolved before matching:

| Spelling | Example |
| --- | --- |
| absolute | `/home/you/.invoker/invoker.db` |
| tilde | `~/.invoker/invoker.db` |
| `$HOME` / `${HOME}` | `$HOME/.invoker/invoker.db` |
| any path ending in the name | `/srv/state/invoker.db` |
| the WAL and shared-memory sidecars | `invoker.db-wal`, `invoker.db-shm` |
| a URI | `file:/home/you/.invoker/invoker.db?mode=ro` |
| a shell variable bound in the same command | `DB=~/.invoker/invoker.db` … `"$DB"` |
| a python variable bound in the same command | `db = "..."` … `connect(db)` |
| an f-string over either | `f"file:{db}?mode=ro"` |

`invoker.db.owner`, `invoker.db.lock` and `invoker.db.bak-*` are **not** the
database. The sidecar markers can be read freely.

**Write** — any of:

- `sqlite3 <target> "UPDATE|INSERT|DELETE|REPLACE|DROP|ALTER|CREATE ..."`, or
  `PRAGMA writable_schema`, including SQL arriving in a heredoc body or
  carried by a value-taking flag ahead of the path (`-cmd "UPDATE ..." <db>`).
- `sqlite3.connect(<target>)` opened read-write — no `file:...?mode=ro` URI
  and no `uri=True`. This fires even when every statement that follows is a
  SELECT: the open itself takes locks against the owner and can recover or
  create a WAL, so the open is the defect and the message names the read-only
  spelling as the fix.
- The same call through whatever alias `import sqlite3 as <name>` bound.
- A mutating `.execute` issued against a connection that *was* opened
  `mode=ro`.

The database is located by scanning every argument of the invocation rather
than by counting position, so a flag that carries its own value cannot push
the path out of the slot it was expected in.

## Stays silent on

- `sqlite3.connect("file:<target>?mode=ro", uri=True)` — including when the
  path arrives through a variable or an f-string.
- A SELECT-only `sqlite3` invocation, and `sqlite3 -readonly`.
- `PRAGMA table_info(...)` and `select ... from sqlite_master` reads.
- Any path that is not Invoker's database, mutating or not.
- Reading the sidecar marker files, or `ls`-ing the database.
- The headless commands this hook redirects to.
- The same SQL as the *content* of a Write or Edit. Only shell-like tool
  names are considered, so writing a script that contains this SQL is never
  blocked — running it is, if the command text shows the write.

## The three outcomes

Found the write, did not find one, and **could not classify the command**.
The third is reported by name and blocked; collapsing it into "clean" is how
a guard reports an unchecked command as safe.

| Outcome | Exit | When |
| --- | --- | --- |
| hit | 2 | a write to the live database is visible in the command |
| clean | 0 | no sqlite entry point, or a read-only one |
| unchecked | 2 | a sqlite entry point the detector could not resolve |

Unchecked covers: a database argument that is a variable the command never
binds; a connect path built by a call (`os.environ[...]`); SQL that is not in
the command at all (`sqlite3 <db> < fix.sql`, `.read`, SQL piped in); and an
invocation that cannot be tokenized. The unchecked message says which of
those it was.

## Fail direction

**Two reads, resolving in opposite directions, on purpose.**

- An **entry point the detector cannot classify fails closed** — blocked, and
  labelled unchecked rather than reported as a hit. The file it might be
  touching is the live one, and a check that could not run is not a pass. To
  narrow the cost, this only applies when the command mentions Invoker at
  all; `sqlite3 "$DB" "UPDATE ..."` in a command with nothing to do with
  Invoker stays silent.
- **Everything else fails open.** An unparseable payload, a missing
  `tool_input`, a non-shell tool, an empty command, and any unexpected
  exception inside the detector all allow the call. The exception path writes
  `invoker-db-guard: detector error, allowing this command: ...` to stderr
  rather than swallowing itself, so a detector bug can only under-block.

## The block message

Every block names the command that owns the state the SQL touches, chosen
from the columns the statement actually assigns:

| What the SQL touches | What the message names |
| --- | --- |
| `tasks.status` | `invoker-cli retry-task <taskId>` / `retry <workflowId>` / `resume <workflowId>` |
| deleting rows from `workflows` or `tasks` | `invoker-cli delete <workflowId>` |
| `tasks.execution_agent`, `pool_id`, `runner_kind`, `pool_member_id`, `remote_target_id` | `invoker-cli route-task <taskId> [--agent\|--pool\|--runner\|--clear-member]` |
| anything else | no headless command covers it — say so, and name adding one as the next step |

`route-task` is named as **landing, not shipped**. A guard that goes quiet
because its replacement has not merged yet teaches the habit it exists to
stop; naming the command that should exist is what turns the block into the
feature request. When it is not there, adding it *is* the task.

The uncovered branch is the load-bearing one. "Use the CLI" with no command
in it is the advice that already lost, so that message states the deficit and
the structural next step instead: stop, and put a concrete plan for the
missing command in front of the user.

## Known false positive

Scoping is per command string, not per statement. One command that opens the
live database read-only and, separately, runs an UPDATE against some other
database is blocked on the pair — split it into two commands. A mutating verb
sitting inside a quoted SQL string literal (`where name = 'delete'`) is also
read as a statement.

## Escape hatch

None. The block is cleared by running the named command, or — when none is
named — by proposing the command that should exist. An env-var override here
would reintroduce the one-keystroke path that the prose already lost to.

## Files

| File | Role |
| --- | --- |
| `detect.py` | the resolver and the three detectors; pure functions |
| `claude_pretooluse.py` | the Claude/Cursor PreToolUse entrypoint |
| `claude.hook.json` | the `PreToolUse` / `Bash` fragment |
| `install_claude_hook.py` | idempotent marker-based settings merge |
| `tests/fixtures/*.json` | one payload per shape, each declaring its outcome and whether the command string is `transcript` or `constructed` |

## Test

```sh
python3 -m unittest discover -s engine/hooks/invoker-db-guard/tests -v
python3 scripts/check_hook_test_coverage.py engine/hooks/invoker-db-guard
```
