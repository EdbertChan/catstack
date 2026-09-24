# handback-needs-attempt

When the assistant hands the user a command or step to perform even though it
did not attempt that command or step in the current turn, ask it to attempt the
work first. The hook uses the shared background `llm-judge` and the phrase
dictionary at
[`engine/hooks/llm-judge/phrases/handback-needs-attempt.json`](../llm-judge/phrases/handback-needs-attempt.json),
so the meaning is judged from the exchange rather than from a local phrase
pattern.

Do not flag a hand-back when the exchange shows that the command was blocked by
a permission denial, sandbox or classifier refusal, or when the step belongs
only to the user: OAuth consent, a password or secret, or physical hardware.
A hand-back after a successful attempt is also clean.

## Next-turn delivery

The Claude `Stop` hook reads the transcript and enqueues a judge job in the
background. The live reply is not held up. On the next turn, the shared
`llm-judge` inbox delivers a hit with instructions to attempt the command or
step first, or to name the exact permission, consent, password, or hardware
boundary that makes it user-only.

The hook skips empty replies, active Stop-hook recursion, and an exact reply
that was already prompted. It sends at most one job for each reply.

If no judge runner answers, or the judge cannot produce a result, the outcome
is **unchecked**. The inbox reports that it could not judge the reply; it does
not treat the result as clean. A clean verdict produces no message.

## Files

- `detect.py` — transcript exchange construction, judge enqueue, and one-shot state
- `claude_stop_check.py` — Claude `Stop` entry point
- `claude.hook.json` — Claude hook registration
- `install_claude_hook.py` — Claude hook installer
- `tests/test_hooks.py` — detector and judge-outcome tests

## Install

Run `./install.sh` from the repository root, then restart Claude.

## Tests

```sh
python3 -m unittest discover -s engine/hooks/handback-needs-attempt/tests -v
python3 scripts/check_skill_file_refs.py
```
