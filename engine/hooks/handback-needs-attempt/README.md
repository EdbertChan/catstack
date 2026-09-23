# handback-needs-attempt

This Claude Stop hook sends the outgoing reply and the current turn's tool calls and results to the shared `llm-judge`. It flags a hand-back that asks the user to run a command or perform a step the agent could have attempted first. A verdict is delivered on the next turn.

It stays silent when the exchange records a permission denial, sandbox or classifier refusal, OAuth consent, password entry, hardware action, or another step only the user can perform. It also stays silent while `stop_hook_active` is set so a rewrite can finish.

The hit message is:

`handback-needs-attempt: this reply hands the user a step the agent could have attempted. Attempt the command first, or name the permission refusal or human-only step that prevents it.`

The hook fails open for an unreadable transcript or an unavailable judge, but reports `unchecked` rather than treating either case as clean. The escape hatch is to let a permission or refusal result appear in the current turn, or explain the human-only requirement in the hand-back.

Meaning is defined by [`handback-needs-attempt.json`](../llm-judge/phrases/handback-needs-attempt.json), not by a regex. The hook queues work in the background and never blocks the outgoing reply.

Tests:

```sh
python3 -m unittest discover -s engine/hooks/handback-needs-attempt/tests -v
python3 scripts/ci/check_hook_test_coverage.py engine/hooks/handback-needs-attempt
```
