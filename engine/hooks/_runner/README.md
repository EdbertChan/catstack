# Hook runner

Usage:

```sh
python3 engine/hooks/_runner/run.py [--timeout SECONDS] <hook>/<script.py> [args...]
```

The runner reads stdin, runs the hook script in a subprocess with that stdin,
passes through the hook's stdout, stderr, and exit code, then appends one JSONL
metrics row.

Hooks need Python 3.11 or newer. The runner itself also runs on older Python,
so it picks the interpreter for the hook: `$CATSTACK_HOOK_PYTHON` when set,
else its own interpreter when that is new enough, else the newest `python3.N`
(N >= 11) on `PATH` or in `/opt/homebrew/bin`, `/usr/local/bin`, `~/.local/bin`
(`$CATSTACK_HOOK_PYTHON_DIRS` replaces that search list). A launcher with a
short `PATH` whose `python3` is the macOS `/usr/bin/python3` (3.9) therefore
still runs hooks on a new Python. When none is found the run fails with one
stderr line naming what it tried, not an import traceback.

## A reply that is only JSON is not judged

Some callers need the agent's last reply to be data, not prose. A headless
`claude -p` run can be told to answer with exactly one JSON object, and the
program that started it parses that reply. The Stop hooks judge prose: word
count, unproven claims, hedges, waits, handoffs. When one of them blocked such
a reply, the agent wrote a second, prose reply to answer the block, and that
prose became its final output, so the caller's JSON parse failed.

So on a `Stop` or `SubagentStop` event the runner does not start the hook when
`last_assistant_message`, with surrounding whitespace removed, parses with
`json.loads` as one JSON object or array. One code fence around the whole reply
(optionally with a language tag) is allowed. The decision is a real JSON parse,
not a text match. Anything else is judged as before: prose around a JSON
snippet, two fences, a bare string or number, JSON that does not parse, or a
payload the runner cannot read. When the payload cannot be read the runner
starts the hook, so the check fails toward judging.

A skipped run exits 0 with no output and writes a metrics row with outcome
`silent` and `"skipped": "machine-deliverable"`. It covers every Stop hook
installed through the runner. A hook run directly, without the runner, is not
covered.

## Doctor

```sh
python3 ~/.claude/hooks/_runner/doctor.py
```

Asks whether the installed hooks can run, from where they are installed.
`install.sh` ends by running it; run it standalone any time without
reinstalling. Four checks, in the order a hook event travels:

| Check | Question |
| --- | --- |
| `runner` | can the runner each harness command names be opened |
| `hooks` | can every installed hook entry script be opened, then imported |
| `end-to-end` | does one real run through the runner reach a hook and come back |
| `effective` | do the installed links point at this checkout |

`hooks` opens before it imports. A link can resolve, `stat()` can succeed, and
`open()` can still fail: a dangling target, an unreadable mode, or a macOS TCC
denial on a checkout under `~/Documents`. Existence tests go through `stat()`,
so they keep passing for the whole of such a denial while every real hook run
dies. When the unreadable target is under `~/Documents`, the report names Full
Disk Access.

`end-to-end` runs `_runner/probe_hook.py`, a hook that prints one marker and
exits, so the run does not write any real hook's state into the session. Its
metrics row goes to a temporary directory, not the real metrics log.

Every check reports `pass`, `fail`, or `unchecked` -- never two outcomes. Exit
0 when everything passed, 1 when something failed, 2 when nothing failed but
something could not be checked.

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
the runner. `scripts/ci/check_install_effective.py` imports `match_direct` from
`wrap_installed.py`, so the install check reports the same direct command form
the wrapper rewrites. Each direct installed hook is reported as:

```text
hook bypasses the metrics runner: <command>
```

Rows are written to `~/.cache/catstack-hook-metrics/runs.jsonl` by default. Set
`CATSTACK_HOOK_METRICS_DIR` to write `runs.jsonl` under a different directory.

Set `CATSTACK_HOOK_PAYLOAD_DIR` to record replayable hook payloads. Recording
is off when the variable is unset. When it is set, the runner writes the raw
event payload bytes before spawning the hook process:

```text
$CATSTACK_HOOK_PAYLOAD_DIR/<event_uid>-<hook>.json
```

`event_uid` is the first 12 hex characters of `sha256(payload_bytes)`, matching
the metrics row. The hook name is sanitized for a filename. Payload recording is
best effort: failures never change hook stdin, stdout, or exit code. Each
payload is capped by `CATSTACK_HOOK_PAYLOAD_MAX_BYTES` (default 256 KiB), and
the directory keeps at most `CATSTACK_HOOK_PAYLOAD_KEEP` files (default 2000)
by deleting the oldest regular files after a successful write.

Each row contains:

- `ts`: UTC timestamp for the recorded run.
- `harness`: `claude`, `cursor`, `codex`, or `unknown`, inferred from the hooks path.
- `hook`: the first path segment from `<hook>/<script.py>`.
- `script`: the rest of the hook script path after `hook`.
- `event`: `hook_event_name` from JSON stdin, or `null`.
- `event_uid`: first 12 hex characters of `sha256(stdin_bytes)`, so hook runs
  from the same harness event can be grouped without coordination. Two
  identical consecutive events can share a uid.
- `session_id`: `session_id` from JSON stdin, falling back to `conversation_id`, or `null`.
- `outcome`: classified result for the run.
- `exit_code`: hook process exit code recorded by the runner.
- `duration_ms`: elapsed runner time in milliseconds.
- `stdout_bytes`: number of stdout bytes emitted by the hook.
- `stderr_tail`: final 500 decoded stderr characters, with invalid UTF-8 replaced.
- `skipped`: present only when the runner did not start the hook; today the
  one value is `machine-deliverable` (see above).

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

## Replay payloads

Use `scripts/test/replay_hook_payloads.py` to compare recorded payloads against
two explicit command sets without reading live harness settings:

```sh
python3 scripts/test/replay_hook_payloads.py \
  --payload-dir /tmp/hook-payloads \
  --fleet fixture="python3 engine/hooks/example/claude_stop.py" \
  --dispatcher fixture="python3 engine/hooks/_runner/dispatch.py fixture"
```

The script runs each `<event_uid>-<hook>.json` payload through the matching
`--fleet <hook>=<command>` and `--dispatcher <hook>=<command>` entries under a
scratch `HOME`, metrics directory, state directories, and findings file. It
prints a table with per-payload match/mismatch columns for stdout, stderr, exit
code, outcome, context, block status, and findings. `--json-out <path>` writes
the same report as JSON. Exit status is 0 only when all compared rows match.

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
