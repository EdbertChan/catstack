# invoker-db-guard

PreToolUse hook (Bash): blocks a direct write to Invoker's live SQLite
database and names the `invoker-cli` command that does the same job.

Invoker's own CLAUDE.md already says "If you are considering direct SQLite
commands, use the corresponding Invoker headless command first" and "If no
corresponding headless command exists, stop and prompt the user with a
concrete plan to add that headless command functionality before
proceeding." That rule is always loaded and still loses to convenience. This
hook is the mechanical half of it.

## What counts as Invoker's database

Any path whose last part is `invoker.db`, `invoker.db-wal`, or
`invoker.db-shm`, however it is spelled: `~/.invoker/invoker.db`,
`$HOME/...`, `${HOME}/...`, `"$HOME"/...`, an absolute path, a `file:` URI,
a bare `invoker.db` after a `cd`, or a variable set earlier in the same
command (`DB=~/.invoker/invoker.db; sqlite3 "$DB" ...`,
`${DB:-~/.invoker/invoker.db}`). That includes the standalone CLI database
under `~/.invoker-cli/`. A backup such as `invoker.db.bak-1200` is not a match.

## Fires on (blocks, exit 2)

- `sqlite3` given `UPDATE`, `INSERT`, `DELETE`, `REPLACE`, `DROP`, `ALTER`,
  `CREATE`, `VACUUM`, `REINDEX`, `ANALYZE`, `PRAGMA writable_schema`, a
  PRAGMA setter that changes the file (`user_version=`, `journal_mode=`), or
  the `.import` / `.restore` dot-commands. The SQL can be an argument, a
  `-cmd`, a heredoc, a here-string, or piped in from `echo` / `printf` / a
  `cat` heredoc. `python3 -m sqlite3` counts as `sqlite3`.
- A Python program (`-c`, heredoc, or stdin) that calls `sqlite3.connect`
  on the database without opening it read-only, or runs a mutating
  `.execute` / `.executemany` / `.executescript` on it. The path is followed
  through Python variables, `os.path.expanduser`, `os.path.join`, f-strings,
  and `pathlib`. Read-only means `mode=ro` (or `immutable=1`) in a `file:`
  URI **and** `uri=True`; `mode=ro` without `uri=True` does not open
  read-only, so it fires.
- A Node program (`node -e`, heredoc) using `node:sqlite` or
  `better-sqlite3` on the database without `readOnly: true`.
- File-level writes to the database files: `rm`, `mv`, `truncate`, `shred`,
  `cp` / `install` / `rsync` / `ln` onto them, `dd of=`, and shell
  redirects (`> ~/.invoker/invoker.db-wal`).

Every stage of the command is checked: the database is found inside
`bash -c`, `eval`, `$(...)`, backticks, `<(...)`, and behind wrappers such
as `timeout`, `env`, `sudo`, and `uv run`. No stage stops the others from
being checked.

## Stays silent on

- A connect using `file:...?mode=ro` with `uri=True`, `sqlite3 -readonly`,
  or `node:sqlite` with `readOnly: true`.
- A `sqlite3` call whose statements are all reads: `SELECT`, `WITH ... SELECT`,
  `EXPLAIN`, `PRAGMA table_info(...)` and the other read PRAGMAs, reads of
  `sqlite_master`, and read dot-commands such as `.schema` and `.tables`.
- A connection-level PRAGMA such as `busy_timeout`, which does not touch
  the file.
- Any database that is not Invoker's, including a Python program that reads
  Invoker read-only and writes only to a scratch database.
- Text that only mentions the database: `ls`, `cp` *from* it to a backup, `grep`,
  `echo`, a commit message, a doc written with `cat > file <<'EOF'`, a PR
  body built with `$(cat <<'EOF' ... EOF)`, and a Python program that only
  holds such a command as string data.
- `invoker-cli` itself.

## The block message

Each write maps to a real command. The message is never a bare "use the CLI":

| The write | The message names |
| --- | --- |
| `tasks.status` | `invoker-cli retry-task <taskId>` / `retry <workflowId>` / `resume <workflowId>` |
| deleting a row from `workflows` | `invoker-cli delete <workflowId>` |
| `tasks.execution_agent` (or `executionAgent` in the task's config JSON) | `invoker-cli set agent <taskId> <agent>` |
| `tasks.pool_id`, `tasks.pool_member_id` | `invoker-cli set pool <taskId> <pool>` |
| `tasks.runner_kind`, `tasks.remote_target_id` | `invoker-cli set executor <taskId> <executor>` |
| a read-write open with no write | how to open read-only, and `invoker-cli query tasks` / `query workflows` |
| anything else | "No headless command covers <the write>", and that the next step is adding one, not writing SQL |

`invoker-cli set` is named and marked **landing**. Invoker's headless
registry has `set` for these task fields and the UI reaches it over REST,
but the CLI does not expose it yet. The message says so, and says to use the
Invoker UI or ask the user until it lands. A guard that stayed quiet because
its replacement is not merged would teach the habit it exists to stop.

Example:

```
invoker-db-guard: blocked a direct write to Invoker's live database (/home/u/.invoker/invoker.db).
What it does: UPDATE tasks SET status.
Invoker's CLAUDE.md: use the headless command, not SQL.
tasks.status -> use one of:
  invoker-cli retry-task <taskId>     one task
  invoker-cli retry <workflowId>      rerun failed tasks, keep completed ones
  invoker-cli resume <workflowId>     pick an incomplete workflow back up
Check the result with `invoker-cli query tasks --workflow <workflowId>`, not SQLite.
```

## Three outcomes, and the fail direction

The detector returns `hit`, `clean`, or `unchecked`. `unchecked` means the
command reaches Invoker's database but the guard cannot see what it does:

- SQL from a file (`sqlite3 ... < fix.sql`, `-init`, `.read`), or piped in
  from a command other than `echo` / `printf` / a `cat` heredoc;
- `sqlite3` on the database with no SQL at all;
- a statement or PRAGMA the guard has no entry for;
- a Python or Node script file that is handed the database path;
- a Python `connect()` whose path is only known at run time, when the
  program or its command line names the database;
- a Python program that does not parse;
- a write whose database path is an unset variable (`sqlite3 "$DB" "UPDATE ..."`).

**`unchecked` fails closed**: it blocks, with its own message that names
what could not be read and how to make the command checkable: put the SQL
inline, open read-only, or use `invoker-cli query`. An exception: read-only
by construction (`sqlite3 -readonly`, a `mode=ro` + `uri=True` connect) is
`clean` even when the SQL is not visible, because it cannot write.

**A broken hook fails open**: if the hook payload is not valid JSON, or the
detector raises, the call is allowed and stderr says
`this call was not checked`. A guard bug must not stop every Bash call.

## Escape hatch

There is no bypass flag, on purpose. If the user approves a one-off
direct write after hearing the plan for a headless command, hand them a
script to run themselves.

## Known gaps

- A Python or shell script file is not opened. If its command line names
  the database it is `unchecked`; if the path lives only inside the file,
  the guard does not see it.
- File operations inside a program (`shutil.copy`, `os.remove`) are not
  checked; only SQLite opens and executes are.
- `ssh host "sqlite3 ..."` is not followed into the remote command.
- Only the Claude harness is wired. Cursor and Codex have no entrypoint yet.

## Files

- `detect.py`: stage analysis, outcome, the block messages, `decide()`.
- `shell.py`: splits a command into stages with quotes, heredocs,
  variables, and substitutions resolved.
- `statements.py`: sorts SQL into write, read, and unknown; names the table and columns.
- `programs.py`: Python (parsed with `ast`) and Node program verdicts.
- `claude_pretooluse_check.py`: the Claude PreToolUse entrypoint.
- `claude.hook.json` / `install_claude_hook.py`: the settings.json merge (idempotent).
- `tests/fixtures/commands_{fire,silent,unchecked}.json`: one command per shape.
- `tests/test_hooks.py`
