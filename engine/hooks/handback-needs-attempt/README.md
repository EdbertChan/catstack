# handback-needs-attempt

Flag a reply that asks the user to run a command or perform a step the
assistant could have attempted in the current turn, when the transcript shows
no prior attempt and no permission prompt, sandbox refusal, or classifier
refusal.

The hook uses the shared background judge and the phrase dictionary in
[`engine/hooks/llm-judge/phrases/handback-needs-attempt.json`](../llm-judge/phrases/handback-needs-attempt.json).
It judges the latest assistant reply together with the turn's tool calls and
results, so it covers direct command hand-backs, requests to continue in a
local IDE, and requests to report completion. It does not use a local phrase
or regular-expression match.

## Exceptions

The hook stays silent when the assistant already attempted the step, or when
the step follows a permission denial, sandbox refusal, or classifier refusal.
It also stays silent for work only the human can do, including entering a
password, granting OAuth consent, connecting physical hardware, or another
human-only action. The assistant should name that reason when handing the
step back.

## Delivery

The Claude `Stop` hook enqueues the judge job in
[`detect.py`](detect.py) and does not hold up the live reply. A hit is delivered
on the next turn through the shared `llm-judge` inbox with this guidance:

> Hand-back needs an attempt: run the command or perform the step yourself
> before asking the user to do it.

The assistant must attempt the command or step first, or explain why only the
user can complete it.

## Unchecked outcome

If the transcript cannot be read, the judge cannot be loaded or enqueued, or
no judge runner can produce a result, the reply is **unchecked**. The inbox
reports “could not judge”; it is not treated as clean. The live reply still
continues without waiting for the background job.

## Files

- `detect.py` — transcript extraction and judge enqueue
- `claude_stop_check.py` — Claude `Stop` entrypoint
- `claude.hook.json` — Claude hook fragment
- `install_claude_hook.py` — idempotent settings merge

## Install

Run `./install.sh` from the repository root, then restart Claude.

## Tests

```sh
python3 -m unittest discover -s engine/hooks/handback-needs-attempt/tests -v
```
