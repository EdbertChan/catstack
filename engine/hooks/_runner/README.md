# Hook runner

Usage:

```sh
python3 engine/hooks/_runner/run.py [--timeout SECONDS] <hook>/<script.py> [args...]
```

The runner reads stdin, runs the hook script in a subprocess with that stdin,
passes through the hook's stdout, stderr, and exit code, then appends one JSONL
metrics row.

## Install

`install.sh` runs `engine/hooks/_runner/wrap_installed.py` after the Claude,
Cursor, and Codex hook installers have updated their harness config files:

- `~/.claude/settings.json`
- `~/.cursor/hooks.json`
- `~/.codex/hooks.json`

The wrapper rewrites installed catstack hook commands from the direct form:

```text
python3 $HOME/.claude/hooks/<hook>/<script.py> [args...]
```

to the runner form:

```text
python3 $HOME/.claude/hooks/_runner/run.py --timeout <seconds> <hook>/<script.py> [args...]
```

The harness name in the path is preserved for Claude, Cursor, and Codex. The
hook identity, script name, and trailing arguments are preserved after the
runner path. Commands that already call `_runner/run.py` are left unchanged.

When a hook entry has a numeric `timeout`, `wrap_installed.py` gives the hook
process half a second less than the harness timeout by passing
`--timeout <timeout - 0.5>` to the runner. Entries without a numeric `timeout`
use `--timeout 59.5`.

`wrap_installed.py` prints one status line per config:

- `skip: <path> missing` when a harness config file is absent.
- `unchecked: <path>: <error>` when a config file cannot be read as JSON.
- `unwrapped: <path>: <command>` for a hook command that references a catstack
  hooks directory but does not match the direct command form.
- `wrapped <count> entr(ies) in <path>` when it rewrites any entries.
- `already up to date: <path>` when no rewrite is needed.

The read-only install checker also verifies that installed hook commands use
the runner. `scripts/check_install_effective.py` imports `match_direct` from
`wrap_installed.py`, so the install check reports the same direct command form
the wrapper rewrites. Each direct installed hook is reported as:

```text
hook bypasses the metrics runner: <command>
```

Rows are written to `~/.cache/catstack-hook-metrics/runs.jsonl` by default. Set
`CATSTACK_HOOK_METRICS_DIR` to write `runs.jsonl` under a different directory.

Each row contains:

- `ts`: UTC timestamp for the recorded run.
- `harness`: `claude`, `cursor`, `codex`, or `unknown`, inferred from the hooks path.
- `hook`: the first path segment from `<hook>/<script.py>`.
- `script`: the rest of the hook script path after `hook`.
- `event`: `hook_event_name` from JSON stdin, or `null`.
- `session_id`: `session_id` from JSON stdin, falling back to `conversation_id`, or `null`.
- `outcome`: classified result for the run.
- `exit_code`: hook process exit code recorded by the runner.
- `duration_ms`: elapsed runner time in milliseconds.
- `stdout_bytes`: number of stdout bytes emitted by the hook.
- `stderr_tail`: final 500 decoded stderr characters, with invalid UTF-8 replaced.

Outcome precedence is:

1. `timed_out` when the runner timeout kills the hook.
2. `blocked` when `exit_code` is `2`.
3. `crashed` when `exit_code` is any other nonzero value.
4. `caught_error` when any stderr line starts with `catstack-hook-error `.
5. `blocked` when stdout is a JSON object with `decision: "block"`, `continue: false`,
   `hookSpecificOutput.permissionDecision: "deny"`, or `permission: "deny"`.
6. `spoke` when stdout has non-whitespace bytes.
7. `silent` otherwise.

If a metrics row cannot be written, the runner appends one stderr line after the
hook stderr:

```text
catstack-hook-metrics: could not write row to <path>: <error>
```

## Report

Usage:

```sh
python3 engine/hooks/_runner/report.py [--since 7d] [--json]
```

`report.py` reads registered catstack hook commands from `~/.claude/settings.json`,
`~/.cursor/hooks.json`, and `~/.codex/hooks.json`, then compares them with rows
from `~/.cache/catstack-hook-metrics/runs.jsonl` by default. Set
`CATSTACK_HOOK_METRICS_DIR` to read `runs.jsonl` from a different directory.
`--since` accepts hour and day windows such as `12h` or `7d`.

The text table header is:

```text
harness hook/script runs spoke silent blocked crashed caught_error timed_out p95_ms last_error
```

Columns:

- `harness`: the harness that owns the installed command or metrics row.
- `hook/script`: the hook name joined to the script path recorded by the runner.
- `runs`: total matching rows in the selected window.
- `spoke`, `silent`, `blocked`, `crashed`, `caught_error`, `timed_out`: counts
  for each recorded outcome.
- `p95_ms`: the 95th percentile of integer `duration_ms` values, or `-` when no
  duration was recorded.
- `last_error`: the first non-empty stderr line from the newest failed row, when
  a failed row recorded one.

Every registered hook gets a row. A registered hook with no rows in the selected
window prints `no record` after `hook/script`; it is not reported as healthy:

```text
cursor hook-b/b.py no record
```

Rows in the log that do not match a currently registered catstack hook are
printed after an `unregistered:` line:

```text
unregistered:
claude loose/z.py 1 0 0 0 0 0 1 10 slow
```

Malformed JSONL rows, non-object rows, rows without parseable timestamps, and
rows outside the `--since` window are skipped. Malformed rows inside the log are
reported before the table as:

```text
skipped <count> malformed row(s)
```

Unreadable harness config files are reported before the table as:

```text
unchecked config: <path>: <error>
```

If the metrics log cannot be read, `report.py` exits `2` and prints one of the
unchecked messages instead of a table:

```text
unchecked: no metrics log at <path>
unchecked: <path>: <error>
```

An unsupported `--since` value also exits `2` and prints:

```text
unsupported --since value: <value>
```

With `--json`, the same report is printed as JSON with `registered`,
`unregistered`, `malformed_rows`, `config_warnings`, and `window_rows`.
