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
- **Stop (blocks, exit 2):** a reply that says it is waiting / watching /
  will report / "nothing needed from you for ~10 minutes" / "N agents still
  running" must name a clock-time ETA (`back at 07:26 UTC`, `by 07:40 UTC`)
  **and** the turn must hold a live wakeup: a `ScheduleWakeup` / `CronCreate`
  call this turn, or a `Monitor` / `Agent` / background Bash whose
  task-notification has not arrived yet. A past clock time ("merged at
  07:24 UTC") is history, not an ETA. Waiting on the user ("waiting on your
  word") is not waiting on a job and passes.

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

## Files

- `detect.py` -- loop / sleep / status-check patterns, wait-language and
  clock-ETA patterns, transcript wakeup state; `decide_pretooluse()`,
  `decide_stop()`.
- `claude_pretooluse.py`, `claude_stop_check.py` -- Claude entrypoints.
- `claude.hook.json` / `install_claude_hook.py` -- settings.json merge for
  both events (idempotent).
- `backtest.py` -- replay over a transcript (`backtest.py X.jsonl`) or over
  the fixtures (`backtest.py --fixtures`); prints would-block counts.
- `tests/fixtures/poll_commands_{fires,silent}.json`,
  `tests/fixtures/wait_replies_{fires,silent}.json` -- sanitized replays of
  the real commands and replies (fires) and their corrected forms (silent).
- `tests/test_hooks.py` -- every fires fixture blocks, every silent fixture
  passes, the backtest reproduces the counts.

Tests: `python3 -m unittest discover -s engine/hooks/wait-needs-wakeup/tests -v`
