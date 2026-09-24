# wait-needs-wakeup

Waiting means scheduling a wakeup, never polling. When the agent is waiting
on something (CI, a merge queue, a subagent, an external job) it hands the
wait to the harness and names a clock-time ETA. Two entrypoints, one rule:

- **PreToolUse on Bash (blocks, exit 2):** a foreground poll loop (`sleep`
  inside a `while` / `until` / retry-`for` over `seq` that checks a status
  with `gh`, `curl`, `grep`, `test`, `ls`, `docker`, ...) or a bare
  foreground `sleep` of 30 seconds or more. A `run_in_background` command
  whose loop exits on its condition (`until`, or a `break`) is the correct
  form and passes: it wakes the agent when the condition is met. A
  background loop with no exit (`while true` and no `break`) is still
  blocked.
- **PreToolUse on ScheduleWakeup (blocks, exit 2):** a wake budget
  (`WAIT_NEEDS_WAKEUP_BUDGET`, default 10). Every ScheduleWakeup resumes
  this same transcript, so wake count x context size is the session's
  poll-check bill — a babysit session once scheduled 109 wakes inside a
  ~500K-token transcript. Past the budget the wait must leave the session:
  a `run_in_background` command that exits on its condition, a `Monitor` /
  `Agent` that notifies once, or compact before waking again. `CronCreate`
  is not budgeted — it spawns a fresh session, so its context does not
  accumulate.
- **Stop (blocks, exit 2):** a reply that says it is waiting / watching /
  will report / "nothing needed from you for ~10 minutes" / "N agents still
  running" must name a clock-time ETA (`back at 07:26 UTC`, `by 07:40 UTC`)
  **and** the turn must hold a live wakeup: a `ScheduleWakeup` / `CronCreate`
  call this turn, or a `Monitor` / `Agent` / background Bash whose
  task-notification has not arrived yet. A past clock time ("merged at
  07:24 UTC") is history, not an ETA. Waiting on the user ("waiting on your
  word") is not waiting on a job and passes.

The guidance ordering is deliberate: detached wakeups (background command
that exits on its condition, Monitor/Agent) are named before
`ScheduleWakeup` because only the detached forms avoid re-sending the
accumulated transcript on every check.

Fail-open on parse or read errors; `stop_hook_active` skips so the rewrite
turn can finish.

## Why

One session ran eleven foreground poll loops (`until grep -q "^exit=" ...;
do sleep 3; done` six times, `for i in $(seq 1 12); ... sleep 5` on
`gh pr view`, a bare `sleep 90` that the harness itself refused with "use
Monitor with an until-loop") and ended twenty-one turns with "A watcher
will ... report all three" or "Nothing needed from you for about 10
minutes" and no next contact time. The harness caught one command; the
user had to say "if an agent is waiting, it must schedule a wakeup. Not
poll."

A later token-burn audit found the flip side: the hook steered agents to
`ScheduleWakeup`, and a multi-day PR-babysit session used it 109 times —
each wake re-sending a ~500K-token transcript, ~3B gross tokens in one
session. Wakeups are a wakeup *mechanism*, not a free wait; the budget cap
exists because a wake inside the same context costs the same as the poll
it replaced.

## Files

- `detect.py` -- loop / sleep / status-check patterns, wait-language and
  clock-ETA patterns, transcript wakeup state; `decide_pretooluse()`,
  `decide_stop()`, and the two backtest entry points `pretooluse_reason()`
  and `replay_stop()`.
- `claude_pretooluse.py`, `claude_stop_check.py` -- Claude entrypoints.
- `claude.hook.json` / `install_claude_hook.py` -- settings.json merge for
  both events (idempotent).
- `tests/fixtures/poll_commands_{fires,silent}.json`,
  `tests/fixtures/wait_replies_{fires,silent}.json` -- sanitized replays of
  the real commands and replies (fires) and their corrected forms (silent).
- `tests/test_hooks.py` -- every fires fixture blocks, every silent fixture
  passes, and the Stop replay agrees with the hook on every fixture.

Tests: `python3 -m unittest discover -s engine/hooks/wait-needs-wakeup/tests -v`

## Backtest against real sessions

Both halves replay over local transcripts through the shared runner,
`scripts/test/backtest_detector.py`:

```sh
python3 scripts/test/backtest_detector.py --detector engine/hooks/wait-needs-wakeup/detect.py:pretooluse_reason --unit tool --tool Bash X.jsonl
python3 scripts/test/backtest_detector.py --detector engine/hooks/wait-needs-wakeup/detect.py:replay_stop --unit rows X.jsonl
```

The first counts the Bash commands the PreToolUse half would block. The
second counts the turn-ending replies the Stop half would block; a wait
reply that already names an ETA and holds a wakeup is listed as a
near-miss. Leave out the path to scan the newest sessions (`--limit N`),
and add `--compare <git-ref>` to see what a change newly blocks or lets
through.
