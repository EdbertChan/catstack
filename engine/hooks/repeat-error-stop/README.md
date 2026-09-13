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

The same signature surviving two edit epochs emits a non-blocking nudge once
per human-prompt span. It fires when one normalized failure signature appears,
a successful edit advances the edit epoch, and that same signature appears
again in the new epoch. It stays silent for these cases: same error twice with no edit in between;
different signatures across edits; any later occurrence after the nudge has
already fired for that signature. The nudge never blocks, never denies a
command, and does not arm `PreToolUse`; it only adds harness context:

```text
repeat-error-stop: this error has now survived N edit(s):
    <sample>
Write down in one sentence the premise those edits shared, then read the source of the check or command that produced this error before editing again.
```

Set `REPEAT_ERROR_STOP_EPOCHS=0` to disable the nudge. As with the block
path, every state read is fail-open: missing, malformed, expired, or an
unreadable state file yields no block, no nudge, and no crash.

## State machine for one signature

Each signature entry stores `count`, `epoch`, `epochs`, `nudged`, and
`commands`. `count` is the number of failures seen in the current edit epoch,
`epoch` is the edit epoch for that count, `epochs` is the list of edit epochs
where the signature has appeared, `nudged` records whether this signature has
already emitted its nudge in the current human-prompt span, and `commands`
remembers normalized shell commands that produced the signature so `PreToolUse`
can deny only after the block threshold.

On failure in the same epoch, the entry increments `count`, records the
command, and blocks when `count` reaches `REPEAT_ERROR_STOP_THRESHOLD`. On
failure in a new epoch, the entry resets `count` and `commands`, records the
new `epoch`, appends it to `epochs`, and emits the nudge when
`len(epochs) >= REPEAT_ERROR_STOP_EPOCHS` and `nudged` is still false. On a
successful edit, the session-level edit epoch advances; entries are not erased,
so the next matching failure can prove that the same signature survived an
edit. On a human prompt, the session state is removed. On TTL expiry, the next
state read returns empty state.

Claude Code fires `PostToolUseFailure` (payload `error` = `Exit code N\n…`)
for failed calls and `PostToolUse` only for successes; both are wired.

Knobs (env): `REPEAT_ERROR_STOP_THRESHOLD` (default 3),
`REPEAT_ERROR_STOP_OBSERVED` (default 1: also count strong error lines in
exit-0 output; 0 = non-zero exits only), `REPEAT_ERROR_STOP_RESET_ON_EDIT`
(default 1), `REPEAT_ERROR_STOP_EPOCHS` (default 2; 0 disables the nudge).
State lives under `~/.cache/catstack-repeat-error-stop/` keyed by session,
expires after 24h, and every hook is fail-open. Missing, unreadable, malformed,
wrong-typed, or expired state means no block and no nudge.

## Backtest against real sessions

`backtest.py` replays Claude Code transcripts through the same `detect.py`
and reports, for every point the hook would have fired, how many identical
errors actually followed (thrash it would have cut) and whether the next real
run of that command succeeded anyway (a premature stop).

```sh
python3 engine/hooks/repeat-error-stop/backtest.py ~/.claude/projects/<project-dir> [...]
REPEAT_ERROR_STOP_OBSERVED=0 python3 engine/hooks/repeat-error-stop/backtest.py ...
python3 engine/hooks/repeat-error-stop/backtest.py --epochs 2 ~/.claude/projects/<project-dir> [...]
```

286 sessions, 38.6k tool results, Aug 2–Sep 1 2026 (Invoker + catstack +
two other repos):

| Mode | Blocks | Later identical errors cut | Premature (same command later succeeded, no edit between) |
| --- | --- | --- | --- |
| **default** (observed + edit reset) | 31 in 20 sessions | 21 | 6 |
| non-zero exits only | 13 | 3 | 4 |
| observed, no edit reset | 75 | 42 | 26 |

Epoch nudge comparison, command:
`python3 engine/hooks/repeat-error-stop/backtest.py --since 2026-08-02 --until 2026-09-02 ~/.claude/projects/-Users-edbertchan-Documents-GitHub-*`.
These rows come from one recorded run over 144 sessions. The counts move as
the set of local transcripts changes, so they are a snapshot, not a target:

| Mode | Fires | Later identical errors saved | Next retry ok | Next retry ok with no edit between |
| --- | ---: | ---: | ---: | ---: |
| default (recorded) | 26 | 7 | 8 | 0 |
| epochs=2 (recorded) | 88 | 39 | 29 | 8 |
| epochs=3 (recorded) | 22 | 12 | 7 | 0 |

`epochs=2` was chosen over `epochs=3` because it caught substantially more
later identical errors, while the no-edit false-positive risk stays advisory:
the nudge adds context but never blocks or denies.

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
| Claude Code | `PostToolUse` (`decision: block`; nudge as `additionalContext`) | `PreToolUse` exit 2 | `UserPromptSubmit` |
| Cursor | `postToolUse` (`additional_context` for block and nudge) | `preToolUse` `continue: false` | `beforeSubmitPrompt` |
| Codex CLI/app | `PostToolUse` (UNVERIFIED schema; block emits `decision` + `additionalContext`; nudge emits `additionalContext`) | native `PreToolUse` `permissionDecision: deny` | `UserPromptSubmit` |

All wrappers share `detect.py`, the state format, and the tests.

## Install

Run `./install.sh`, then restart Claude Code, Cursor, and Codex.

## Tests

```sh
python3 -m unittest discover -s engine/hooks/repeat-error-stop/tests -v
python3 scripts/check_hook_test_coverage.py engine/hooks/repeat-error-stop
```
