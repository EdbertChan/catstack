# handback-needs-attempt

When the assistant hands a runnable command or step back to the user without
trying it first, send a follow-up on a later turn telling the assistant to
attempt it or name the concrete human-only blocker.

The hook does not decide that from local wording rules. On every Stop it hands
the current turn's exchange and the outgoing reply to the background judge
using
[`engine/hooks/llm-judge/phrases/handback-needs-attempt.json`](../llm-judge/phrases/handback-needs-attempt.json).
It flags a reply that asks the user to run a command or do a step themselves
when the exchange shows no prior attempt by the assistant and no permission,
sandbox, classifier, or tool refusal before the hand-back.

Stay silent when the assistant already attempted the step, when a permission
prompt or tool refusal came first, or when the step requires OAuth consent, a
password, hardware, or another concrete action only the user can perform.

A hit arrives on a later turn through the shared [`llm-judge`](../llm-judge/README.md)
inbox and carries the dictionary's `on_hit` text. The live reply is never held
up. If the judge result was unchecked, the inbox reports "could not judge" and
"unchecked, not clean" instead of treating the reply as clean. Clean verdicts
show nothing. Fail open.

Once per reply, with a two-hour marker TTL. Skip if `stop_hook_active` is set,
if the transcript or reply is missing, or if the transcript cannot be read.
The supported escape is naming the concrete human-only blocker in the reply.

## Model-judged path

`enqueue_judge` in `detect.py` resolves the transcript, takes the outgoing
reply, builds the current exchange from the person's last message onward, and
sends a phrase-dictionary job to `llm-judge`. The dictionary defines the
meaning with `match` and `not_match` examples and supplies the static `on_hit`
follow-up text.

The exchange includes the person's message, assistant replies, and tool-result
records from the current turn so the judge can see whether the agent attempted
the step or hit a permission/refusal boundary before handing it back. Harness
metadata and sidechain rows are ignored.

The model call runs in a detached background process, so the reply is never
held up. The verdict reports one turn later through the shared inbox. A hit
shows the dictionary's `on_hit` text. If no runner could answer, or the result
could not be checked, the inbox says the verdict was unchecked instead of
staying quiet. A clean verdict shows nothing.

`llm-judge` is loaded from the sibling folder (`../llm-judge/judge.py`), which
sits next to this one in the repo and in each harness's `hooks/` folder. If it
cannot be loaded, if enqueueing fails, or if the transcript cannot be read, the
hook writes a `catstack-hook-error handback-needs-attempt: ...` message to
stderr and its exit status and output stay the same.

To grow coverage, add the real text of any miss to the dictionary's `match`
phrases, or the real text of any false alarm to `not_match`. Do not add a
pattern to this hook; the prose meaning belongs in the phrase dictionary.

## Files

- `detect.py` - judge enqueue + once-per-reply state
- `claude_stop_check.py` - Claude `Stop`
- `install_claude_hook.py` / `claude.hook.json`

## Install

`./install.sh` from the repo root. Restart the harness.

## Tests

```sh
python3 -m unittest discover -s engine/hooks/handback-needs-attempt/tests -v
python3 scripts/check_skill_file_refs.py
```
