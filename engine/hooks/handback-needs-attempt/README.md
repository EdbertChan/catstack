# handback-needs-attempt

When the assistant tells the user to run a command or perform a step
themselves without attempting it in the current turn, flag the reply on a
later turn.

The hook does not decide that from local wording rules. On every Stop it hands
the last assistant reply and the current exchange to the background judge using
[`engine/hooks/llm-judge/phrases/handback-needs-attempt.json`](../llm-judge/phrases/handback-needs-attempt.json).
A hit arrives on a later turn through the shared [`llm-judge`](../llm-judge/README.md)
inbox and carries the dictionary's `on_hit` text. The live reply is never held
up. If the judge result was unchecked, the inbox reports "could not judge"
instead of treating the reply as clean. Fail-open.

Flag examples include "Please run: invoker-cli setup slack ... then tell me
when it completes", "Now on your end in Xcode:", or asking the user to run a
bash script, when no attempt happened in the same turn.

Do not flag a hand-back that follows a permission denial, sandbox refusal,
classifier refusal, or tool refusal. Do not flag a step only the person can do,
such as entering a password, granting OAuth consent in a browser, or using
hardware. Do not flag when the assistant already attempted the command or step
and is reporting the result.

## Model-judged path

`enqueue_judge` in `detect.py` reads the transcript, takes the current reply,
builds a phrase-dictionary job, attaches the current exchange as
`tool_calls_and_results`, and sends it to `llm-judge`. The dictionary defines
the meaning with `match` and `not_match` examples and supplies the static
`on_hit` follow-up text.

No job is sent when `stop_hook_active` is set, when the transcript path is
missing, or when the reply is empty. User rows that are metadata, sidechains,
or tool results are excluded when finding the current exchange, so the window
starts from the person's last real message.

The model call runs in a detached background process, so the reply is never
held up. Runners are tried in `llm-judge` order, first answer wins.

The verdict reports one turn later. On the next prompt the `llm-judge` inbox
shows a hit as the dictionary's `on_hit` text. If no runner could answer, or
the result could not be checked, the inbox says "could not judge" instead of
staying quiet. A clean verdict shows nothing.

If the transcript cannot be read, or the judge cannot be loaded or enqueued,
the hook writes `handback-needs-attempt: unchecked: <error>` to stderr and its
exit status and output stay the same.

To grow coverage, add the real text of any miss to the dictionary's `match`
phrases, or the real text of any false alarm to `not_match`. Do not add a
pattern to this hook; the prose meaning belongs in the phrase dictionary.

## Files

- `detect.py` - judge enqueue
- `claude_stop_check.py` - Claude `Stop`
- `install_claude_hook.py`

## Install

`./install.sh` from the repo root. Restart the harness.

## Tests

```sh
python3 -m unittest discover -s engine/hooks/handback-needs-attempt/tests -v
python3 scripts/check_skill_file_refs.py
```
