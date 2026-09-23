# handback-needs-attempt

When the assistant hands the user a command or step the agent could have
attempted first, inject a follow-up on a later turn telling the agent to try
the work or name why only the user can do it.

The hook does not decide that from local wording rules. On every Stop it hands
the last assistant reply plus the current turn's tool calls and results to the
background judge using
[`engine/hooks/llm-judge/phrases/handback-needs-attempt.json`](../llm-judge/phrases/handback-needs-attempt.json).
A hit arrives on a later turn through the shared [`llm-judge`](../llm-judge/README.md)
inbox and carries the dictionary's `on_hit` text. The live reply is never held
up. If the judge result was unchecked, the inbox reports "could not judge"
instead of treating the reply as clean. Fail-open.

Flag examples: "Please run: invoker-cli setup slack ... then tell me when it
completes", "Now on your end in Xcode", or "run the bash script yourself"
when the turn has no prior attempt by the agent.

Stay silent when the exchange records a permission denial, sandbox refusal,
classifier refusal, password entry, OAuth consent, hardware action, or another
step only the user can perform. A hand-back after one of those blockers is the
right outcome, not a violation. Stay silent while `stop_hook_active` is set so
a rewrite can finish.

Once per reply. Assistant text only - user messages and fenced examples stay
silent by way of the judge dictionary.

## Model-judged path

`enqueue_judge` in `detect.py` reads the transcript, takes the current reply,
adds the current turn's tool calls and tool results, builds a phrase-dictionary
job, and sends it to `llm-judge`. The dictionary defines the meaning with
`match` and `not_match` examples and supplies the static `on_hit` follow-up
text:

```text
handback-needs-attempt: this reply hands the user a step the agent could have attempted. Attempt the command first, or name the permission refusal or human-only step that prevents it.
```

No job is sent when `stop_hook_active` is set, when this exact reply and
exchange were already prompted, when the reply is empty, or when no transcript
is available. The one-shot key is the transcript path plus a hash of the reply
text and exchange, so the same reply with different tool evidence can still be
judged.

The exchange starts at the person's latest message and includes every tool call
and tool result after it. That evidence is what keeps permission denials,
sandbox or classifier refusals, OAuth consent, passwords, and physical-device
steps silent. If there was no attempt, the prompt explicitly says
`TURN TOOL CALLS AND RESULTS:\nnone`.

The model call runs in a detached background process, so the reply is never
held up. The verdict reports one turn later. On the next prompt the
`llm-judge` inbox shows a hit as the dictionary's `on_hit` text. If no runner
could answer, or the result could not be checked, the inbox says "could not
judge" instead of staying quiet. A clean verdict shows nothing.

If the transcript cannot be found or read, the hook writes
`handback-needs-attempt: unchecked, letting this reply through: <reason>` to
stderr and still lets the reply through. If enqueueing raises unexpectedly, the
hook writes `catstack-hook-error handback-needs-attempt: <error>` to stderr and
fails open.

To grow coverage, add the real text of any miss to the dictionary's `match`
phrases, or the real text of any false alarm to `not_match`. Do not add a
pattern to this hook; the prose meaning belongs in the phrase dictionary.

## Files

- `detect.py` - judge enqueue + once-per-reply state
- `claude_stop_check.py` - Claude `Stop` entrypoint
- `claude.hook.json` - Claude hook fragment
- `install_claude_hook.py` - Claude settings merge

## Install

`./install.sh` from the repo root. Restart Claude.

## Tests

```sh
python3 -m unittest discover -s engine/hooks/handback-needs-attempt/tests -v
python3 scripts/ci/check_hook_test_coverage.py engine/hooks/handback-needs-attempt
```
