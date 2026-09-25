# handback-needs-attempt

The Stop hook asks the shared background `llm-judge` whether the assistant's
last reply tells the user to perform a command or step that the assistant did
not attempt during the current turn. The judge receives the reply plus the
turn's tool calls and results, so a refusal or human-only blocker can keep the
hook silent. A hit arrives on a later turn through the `llm-judge` inbox; the
reply is never held up.

## Fires on

- `Please run: invoker-cli setup slack ... then tell me when it completes`
- `Simulator build still passes. Now on your end in Xcode:`
- equivalent hand-backs where the turn contains no attempt at the handed-over
  command or step

## Silent on

- a permission denial, sandbox refusal, or classifier refusal in the turn
- a password, OAuth consent, hardware action, or operating-system approval
  that only the human can perform
- a command or step the assistant already attempted in the turn
- questions, plans, offers, quoted examples, and judge-clean replies

The inbox message on a hit is:

> handback-needs-attempt: this reply hands the user a command or step the agent
> could have attempted. Attempt it first, or name the permission refusal or
> human-only blocker that makes the step theirs.

## Fail direction

The hook fails open because the reply has already been sent. A missing or
unreadable transcript is reported as `unchecked`, and a judge that cannot
answer reaches the inbox as `could not judge`; neither is treated as clean.
The escape hatch is to turn `CATSTACK_REFLECT_ENFORCEMENT` off.

## Files

- `detect.py` builds the exchange from the current turn and queues the judge.
- `claude_stop_check.py` is the non-blocking Claude Stop entrypoint.
- `claude.hook.json` and `install_claude_hook.py` merge the Stop hook into
  Claude settings.
- `tests/test_hooks.py` covers positive hand-backs, refusals, OAuth consent,
  unreadable input, tool evidence, and unchecked judge results.

Tests: `python3 -m unittest discover -s engine/hooks/handback-needs-attempt/tests -v`
