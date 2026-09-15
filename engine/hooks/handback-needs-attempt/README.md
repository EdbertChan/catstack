# handback-needs-attempt

This background-judged `Stop` hook catches a reply that asks the user to run
a command or perform an actionable setup step when the agent did not attempt
it in the current turn. The hook sends the reply plus the current turn's
tool calls and results to the shared `llm-judge`; a hit is delivered on the
next turn.

It stays silent after a permission denial, sandbox or classifier refusal, and
for steps only a human can perform, including passwords, OAuth consent, and
hardware actions. It also stays silent when the step was already attempted or
the reply only quotes or describes a hand-back.

The block message is:

> handback-needs-attempt: this reply asks the user to perform a step the agent
> could have attempted in this turn. Attempt the command or step first, or
> name the permission, sandbox, classifier, or human-only reason that makes it
> impossible here.

## Next-turn delivery

The Stop hook queues the judge job in the background, so it never delays the
reply that it is checking. On the next turn, the shared `llm-judge` inbox
delivers the block message above when the judge returns a hit. A clean verdict
delivers nothing.

## Fail direction

The hook fails open when the transcript is missing, unreadable, or malformed,
so an input it cannot inspect is never treated as an unattempted hand-back.
If no judge runner answers, or the judge result cannot be checked, the shared
judge delivers an `unchecked` message saying it could not judge the last reply;
unchecked is never treated as clean. `stop_hook_active` returns immediately so
a rewritten reply can finish.

## Install and tests

Run `./install.sh` and restart Claude Code. The installer merges the `Stop`
entry idempotently, and the stop manifest is mirrored to `SubagentStop`.

```sh
python3 -m unittest discover -s engine/hooks/handback-needs-attempt/tests -v
python3 scripts/ci/check_hook_test_coverage.py engine/hooks/handback-needs-attempt
python3 scripts/check_skill_file_refs.py
```
