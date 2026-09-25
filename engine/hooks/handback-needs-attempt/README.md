# handback-needs-attempt

When the assistant tells the user to run a command or perform a step that the
assistant could have attempted during the current turn, report that hand-back
on the next turn.

The hook does not decide that from local wording rules. On every eligible
Claude Stop it sends the last assistant reply and the current turn's tool calls
and results to the background judge using
[`engine/hooks/llm-judge/phrases/handback-needs-attempt.json`](../llm-judge/phrases/handback-needs-attempt.json).
A hit arrives on the next turn through the shared
[`llm-judge`](../llm-judge/README.md) inbox and tells the assistant to attempt
the command first or name the blocker that makes it the user's step. The live
reply is never held up.

A hand-back stays clean when an earlier tool result shows a permission denial,
a sandbox or classifier refusal, or a step that only the user can complete,
such as entering a password, granting OAuth consent, interacting with hardware,
or approving an operating-system dialog. A question, plan, offer, or report of
an attempted command is not a hand-back either.

If no judge runner can answer, the next-turn inbox reports that the reply
"could not judge" and is unchecked, not clean. If the transcript or assistant
reply cannot be read before a job is queued, the Stop hook writes a
`catstack-hook-unchecked handback-needs-attempt` diagnostic to stderr. Both
paths fail open because the reply has already been sent.

## Model-judged path

`enqueue_judge` in `detect.py` finds the current turn at the person's latest
message, collects tool calls and tool results from that turn, appends the last
assistant reply, builds a phrase-dictionary job, and sends it to `llm-judge`.
The dictionary defines the meaning with `match` and `not_match` examples and
supplies the static `on_hit` follow-up text.

No job is sent when `stop_hook_active` is set, when reflect enforcement is off,
or when there is no readable transcript and non-empty assistant reply. A tool
result does not start a new turn, so a denial or human-only blocker remains in
the exchange the judge sees. Harness metadata and subagent rows do not count as
the person's latest message.

The model call runs in a detached background process. The verdict is drained
through the shared inbox on the next prompt or tool event. A hit shows the
dictionary's `on_hit` text, a clean verdict shows nothing, and an unchecked
verdict explicitly says that the check did not run successfully.

To grow coverage, add the real text of any miss to the dictionary's `match`
phrases, or the real text of any false alarm to `not_match`. Do not add a
pattern to this hook; the prose meaning belongs in the phrase dictionary.

## Files

- `detect.py` - current-turn exchange construction and judge enqueue
- `claude_stop_check.py` - Claude `Stop` wrapper
- `claude.hook.json` - Claude hook declaration
- `install_claude_hook.py` - idempotent Claude settings merge
- `tests/test_hooks.py` - flag, exception, delivery, and unchecked coverage

## Install

Run `./install.sh` from the repository root, then restart Claude.

## Tests

```sh
python3 -m unittest discover -s engine/hooks/handback-needs-attempt/tests -v
python3 scripts/check_skill_file_refs.py
```

## Off unless you opt in

This hook is part of the reflect/automate-me class and does nothing unless
`CATSTACK_REFLECT_ENFORCEMENT` is on:

```sh
echo 'CATSTACK_REFLECT_ENFORCEMENT=1' >> ~/.catstack.env
```

The process environment, `$CATSTACK_ENV_FILE`, the repository's `.env`, and
`~/.catstack.env` are consulted in that order. See
[`engine/hooks/_flags/README.md`](../_flags/README.md).
