# handback-needs-attempt

This Stop hook sends the outgoing reply and the current turn's tool calls and
results to the shared `llm-judge`. It fires when the reply hands the user a
command or step the assistant could have attempted, and the exchange shows no
attempt before the hand-back.

It stays silent when the assistant already attempted the step, when a
permission prompt or tool refusal came first, or when the step requires an
OAuth approval, password, hardware action, or another concrete action only the
user can perform. The exact meaning lives in
[`engine/hooks/llm-judge/phrases/handback-needs-attempt.json`](../llm-judge/phrases/handback-needs-attempt.json).

On a hit, the next turn tells the assistant to attempt the command first or
name why only the user can do it. A judge failure is reported as unchecked,
never as clean. The live reply is not held while the background judge runs.
Each reply is queued once, with a two-hour marker TTL.

The hook fails open when its transcript cannot be read, when no transcript is
available, or when the Stop payload is malformed. `stop_hook_active` returns
early so a rewritten reply is not looped.

It has no user-configurable escape hatch: the supported escape is naming the
concrete human-only blocker in the reply.

## Tests

```sh
python3 -m unittest discover -s engine/hooks/handback-needs-attempt/tests -v
```
