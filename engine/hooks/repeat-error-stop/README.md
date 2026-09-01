# repeat-error-stop

Mechanical stop for the blind re-run loop: the same command, the same error,
three times, with nothing changed in between. Every failed tool call (and, in
the default *observed* mode, every error line seen in exit-0 output such as a
`tail` of a test log) is reduced to a signature: numbers, hashes, quoted
names, timestamps, and paths are blanked, so `Task "alpha" did not reach
status within 55000ms` and `Task "beta" did not reach status within 55000ms`
count as the same error. On the third identical signature in one session:

1. `PostToolUse` returns `decision: block` with the error sample and the
   instruction to stop re-running and report (error verbatim, what was
   tried, what was ruled out; or a new hypothesis before a different command).
2. `PreToolUse` denies any shell command whose normalized text already
   produced that signature, until the human sends a new prompt.
3. `UserPromptSubmit` from a human resets the counters. `/loop` firings,
   `<task-notification>` wakeups, and autonomous-loop sentinels do not.
4. A successful `Edit`/`Write` restarts the count for every signature: an
   edit-then-revalidate loop (`validate-pr-body` failing three times while the
   body is being fixed) is iteration, not a blind re-run.

Claude Code fires `PostToolUseFailure` (payload `error` = `Exit code N\n…`)
for failed calls and `PostToolUse` only for successes; both are wired.

Knobs (env): `REPEAT_ERROR_STOP_THRESHOLD` (default 3),
`REPEAT_ERROR_STOP_OBSERVED` (default 1: also count strong error lines in
exit-0 output; 0 = non-zero exits only), `REPEAT_ERROR_STOP_RESET_ON_EDIT`
(default 1). State lives under `~/.cache/catstack-repeat-error-stop/` keyed
by session, expires after 24h, and every hook is fail-open.

## Backtest against real sessions

`backtest.py` replays Claude Code transcripts through the same `detect.py`
and reports, for every point the hook would have fired, how many identical
errors actually followed (thrash it would have cut) and whether the next real
run of that command succeeded anyway (a premature stop).

```sh
python3 engine/hooks/repeat-error-stop/backtest.py ~/.claude/projects/<project-dir> [...]
REPEAT_ERROR_STOP_OBSERVED=0 python3 engine/hooks/repeat-error-stop/backtest.py ...
```

286 sessions, 38.6k tool results, Aug 2–Sep 1 2026 (Invoker + catstack +
two other repos):

| Mode | Blocks | Later identical errors cut | Premature (same command later succeeded, no edit between) |
| --- | --- | --- | --- |
| **default** (observed + edit reset) | 31 in 20 sessions | 21 | 6 |
| non-zero exits only | 13 | 3 | 4 |
| observed, no edit reset | 75 | 42 | 26 |

Thrash it would have stopped: a session that re-ran `cd <dir> && git …` into
a non-repo 15 more times after the third `fatal: not a git repository`; a
merge that hit the same `CONFLICT (content)` again; a remote `gh api` call
failing identically over ssh. Premature stops it would have caused: a
`gh pr merge` that failed on conflicts once more and then succeeded (someone
else moved the queue); a `python3 -c` traceback fixed by a `sed`, which is
not an `Edit` tool so did not reset the count; a `grep` argument error fixed
on the next call; two log tails of a remote service that kept printing an
old error. Six premature stops in 286 sessions, each costing one
"state a new hypothesis" turn, against 21 blind re-runs cut.

Why not stricter: exits-only catches almost nothing here because the real
loops read failures from log tails and test summaries that exit 0.

## Harness support

| Harness | Count | Deny re-run | Reset |
|---|---|---|---|
| Claude Code | `PostToolUse` (`decision: block`) | `PreToolUse` exit 2 | `UserPromptSubmit` |
| Cursor | `postToolUse` (`additional_context`) | `preToolUse` `continue: false` | `beforeSubmitPrompt` |
| Codex CLI/app | `PostToolUse` (UNVERIFIED schema; emits `decision` + `additionalContext`) | native `PreToolUse` `permissionDecision: deny` | `UserPromptSubmit` |

All wrappers share `detect.py`, the state format, and the tests.

## Install

Run `./install.sh`, then restart Claude Code, Cursor, and Codex.

## Tests

```sh
python3 -m unittest discover -s engine/hooks/repeat-error-stop/tests -v
python3 scripts/check_hook_test_coverage.py engine/hooks/repeat-error-stop
```
