# categorical-scope-guard

A `PreToolUse` hook on `Bash`. When the live human instruction quantifies a
target with **all / every / each / the whole / any and all** ("make all
tasks use claude"), it blocks a command that mutates that target through a
status or state filter. A judgment about which members are relevant does not
replace a categorical word the user said.

This is the positive half of the categorical-constraint rule in `cat-mode`,
which lists `only`, `never`, `any`, `no`, `do not`, `all`, `every`, and
`each`.

## Fires on

Both must hold.

1. **A categorical scope attached to a noun** in the live instruction:
   `all`, `every`, `each`, `the whole`, `any and all`, or `everything in`,
   then an optional `of` / `the` / `these` / `our` …, up to three modifier
   words, then the target noun — "all tasks", "every workflow", "all the
   PRs", "each pull request", "all the catstack prs". A bare "all" that is
   not attached to a noun ("all right", "that's all") is not a scope.
2. **The command mutates that same noun through a status/state filter.**
   - SQL `update <table> set … where … status in / not in / = / != / <> …`
     or `delete from <table> where status …`, anywhere in the command text,
     including a Python heredoc. An id-keyed update (`where id=?`) counts
     when the same command selects its ids from that table with a status
     filter.
   - `gh pr|issue list --state X`, `gh run list --status X`, and
     `invoker-cli query tasks|workflows --status X`, when the listing feeds
     a mutation: it sits inside `$(…)`, `<(…)` or backticks (not an `echo` /
     `printf` display), or it pipes into `xargs`, `while`, `for`, or a
     mutating stage; and the command mutates the same noun (`gh pr
     edit|merge|close|…`, `gh api` writes to `pulls`/`issues`, `gh issue …`,
     `gh run cancel|rerun|delete`, `invoker-cli retry…|resume|delete…`,
     `invoker-ui … set task`, or an SQL update/delete on the table).
   - A later stage of that pipeline narrowing it: `jq select(.status ==
     "x")`, a `grep` whose pattern is only status words, or a Python
     `t['status'] in (…)`. A name bound to a literal set in the same command
     is resolved, and `…: continue` reads as a drop.
   - `invoker-cli retry-tasks --status X`.

Nouns are compared after singularising, so the SQL table `tasks`, the CLI
subcommand `query tasks`, and the words "task" / "tasks" are one noun.

## The live instruction

The newest four genuine human turns. For each noun the command filters, the
newest turn that quantifies that noun decides: a categorical phrase arms the
guard, a named subset silences it. Four turns, because a categorical
instruction is usually followed by short refinements that never repeat the
word ("just do it ad hoc for now", "just use the local-only pool"); the
corpus backtest needed four turns to see through three of them.

A genuine human turn is text the human typed. Tool results, task
notifications, Stop-hook feedback, skill injections, teammate messages,
compact summaries, local-command output and `<bash-input>` are skipped. A
slash command counts by its arguments. Fenced blocks (with a closing fence),
blockquote lines, inline code and double-quoted spans are stripped before
matching, and a turn longer than 800 characters is read only at its first
and last 400 — where a live directive sits in a paste.

## Stays silent on

- **The user named the subset:** "all the pending ones", "every failed
  task", "set the pending tasks to claude", "all open PRs". A subset named
  only inside a state question ("are all failed tasks and pending tasks
  using X? Yes or no?") checks state rather than setting scope, so it does
  not silence an earlier "all tasks".
- **The filter is the complete set:** `--state all`, or a `status in (…)`
  that lists every value. Known sets: Invoker task statuses (13), Invoker
  workflow statuses (10), PR `open|closed|merged`, issue `open|closed`.
- **Read-only work:** a listing that is only displayed or counted, and any
  `--dry-run`.
- **No categorical word** in the live window, including a negated one ("not
  all tasks") or one inside quoted or fenced text.
- **A different noun:** "tag all the PRs" does not arm the guard for an
  `update tasks … where status …`.
- **A stated complete set:** a line starting `Complete set:` in the
  assistant's own text after the latest human turn.

## Block message

```
categorical-scope-guard: you said "can you make all tasks use claude and local executor". "all tasks" names every task, and this command narrows tasks by a status filter:
  - `status in ('pending','queued')` (keeps only pending, queued)
Do one of two things:
  1. Drop the filter, so the command covers every task there is.
  2. Or write a line `Complete set: <why this subset is every task there is>` in your reply, then re-run the same command.
```

## Three outcomes, and the fail direction

- **HIT** — exit 2 with the message above.
- **CLEAN** — exit 0.
- **UNCHECKED** — exit 2. **This hook fails closed.** It blocks, and says
  `UNCHECKED`, when:
  - the transcript path is absent, the file is missing, a line is malformed
    JSON (a torn final line is tolerated), the window runs past the 64 MB
    scan cap, or no human turn is found;
  - the filter's values cannot be read: `?`, `{…}`, `%s`, `$VAR`, or a
    `where` clause built by string concatenation;
  - the detector raises.

The transcript is read only after the command is found to carry a
status-filtered mutation, so an unreadable transcript never blocks an
ordinary command.

The one fail-open case: a hook payload that is not JSON carries no command
to classify. It is logged to stderr and allowed.

## Escape hatch

Drop the filter, or write `Complete set: <why the subset is every X there
is>` on its own line in the reply, then re-run. The line is read from the
transcript, so a harness that does not write assistant text to the
transcript before the tool runs cannot see it; there, end the turn with the
reason and let the user answer.

## Known misses

- A script written with the Write tool and run by path (`bash /tmp/x.sh`).
  The hook classifies the command text, not the file it names.
- A mutation set built through intermediate files (listing → JSON file →
  Python filter → ops file → `xargs`).
- `gh … --search "is:open"`, MCP tools (the matcher is `Bash`), and a
  categorical word said more than four human turns back.
- The status sets are copies, keyed by noun. If Invoker adds a status, a
  filter listing every old one reads as a narrowing, and a `tasks` table in
  some other database is checked against Invoker's set. Both fail toward
  blocking; `Complete set:` clears them.

## Files

- `detect.py` — command parser, human-turn reader, `decide()`.
- `claude_pretooluse.py` — the entrypoint.
- `claude.hook.json`, `install_claude_hook.py` — the settings merge that
  `install.sh` runs.
- `tests/test_hooks.py`, `tests/fixtures/` — the fixtures are real commands
  copied verbatim from a transcript.
