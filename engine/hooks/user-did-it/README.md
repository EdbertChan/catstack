# user-did-it

UserPromptSubmit hook: when the user's new message shows they did by hand a
step the agent could have done, the background judge flags it. What the user
did is the spec for what the agent should have done. A hit arrives on a later
turn through the shared [`llm-judge`](../llm-judge/README.md) inbox and tells
the agent to take that kind of step itself and to name it as a User-did-it
finding when [`reflect`](../../skills/reflect/references/lenses.md) runs. The
prompt is never held up.

Off unless `CATSTACK_REFLECT_ENFORCEMENT` is on, like the other reflect hooks.

## Fires on (judged)

Whether the message reports a hand-done step is meaning, so the model judges
it from [`user-did-it.json`](../llm-judge/phrases/user-did-it.json):

- a command run in the user's own terminal, usually pasted with its output
- a file the user edited, or a fix the user wrote and pasted in
- a fact the user looked up for the agent

## Silent on

- steps that physically need the person: a password or 2FA code, plugging in
  hardware, an operating-system approval dialog, filming (judged)
- requests, questions, and plans the user has not done yet (judged)
- machine relays that arrive shaped like a prompt: task notifications, Stop
  hook feedback, system notifications, context-continuation summaries
  (checked locally in `detect.py`, never sent to the judge)

To grow coverage, add the real text of a miss to the dictionary's `match`
phrases, or of a false alarm to `not_match`. Do not add a pattern to this hook.

## Fail direction

Fails open: the hook never blocks. A payload with no prompt text, no
transcript path, or unreadable JSON is written to stderr as
`catstack-hook-unchecked user-did-it`, not treated as clean. An unloadable
dictionary or judge is logged as `catstack-hook-error user-did-it`. If the
judge could not answer, the inbox says "could not judge". Escape hatch: turn
`CATSTACK_REFLECT_ENFORCEMENT` off.

## Files

- `detect.py` -- which prompts are the person, the enforcement gate, and the judge job.
- `claude_prompt_submit.py` -- Claude UserPromptSubmit entrypoint.
- `eval_dictionary.py` -- asks the real judge six cases; not run in CI, which has no model access.
- `claude.hook.json` / `install_claude_hook.py` -- settings.json merge (idempotent).
- `tests/test_hooks.py` -- relay filtering, the flag gate, unchecked payloads, and inbox delivery with a fake judge.

Tests: `python3 -m unittest discover -s engine/hooks/user-did-it/tests -v`
