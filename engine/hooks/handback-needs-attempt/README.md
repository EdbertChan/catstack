# handback-needs-attempt

When the assistant hands the user a command or step the agent could have tried
itself, inject a follow-up on a later turn telling the agent to attempt it
first or name why only the user can.

The hook does not decide that from local wording rules. On every Stop it hands
the last assistant reply plus the current turn's tool calls and results to the
background judge using
[`engine/hooks/llm-judge/phrases/handback-needs-attempt.json`](../llm-judge/phrases/handback-needs-attempt.json).
A hit arrives on a later turn through the shared [`llm-judge`](../llm-judge/README.md)
inbox and carries the dictionary's `on_hit` text. The live reply is never held
up. If the judge result was unchecked, the inbox reports "could not judge"
instead of treating the reply as clean. Fail-open.

Flag the hand-back when the reply asks the user to run a command or perform a
step and the same turn does not show that the agent already attempted it.

Stay silent when the hand-back follows a permission denial, sandbox or
classifier refusal, or a step only a human can perform: password entry, OAuth
consent, hardware access, physical device interaction, and similar boundaries.

Once per reply and tool-exchange pair. Assistant text only - user messages and
fenced examples stay silent.

## Model-judged path

`enqueue_judge` in `detect.py` reads the transcript, takes the current reply,
collects tool calls and tool results since the person's last message, builds a
phrase-dictionary job, and sends it to `llm-judge`. The dictionary defines the
meaning with `match` and `not_match` examples and supplies the static `on_hit`
follow-up text.

No job is sent when `stop_hook_active` is set, when this exact reply and tool
exchange were already prompted, when the transcript cannot be found, when the
transcript cannot be read, or when the reply is empty. If a payload names no
readable transcript, or names a transcript that cannot be read, the hook writes
`handback-needs-attempt: unchecked, letting this reply through: <reason>` to
stderr rather than treating the reply as clean.

The one-shot key is the transcript path plus a hash of the reply text and the
turn's tool exchange. Keying on the exchange matters because the same reply
after an attempted command is different from the same reply with no attempt.
The turn runs from the person's own last message to the end of the file, so
permission denials, refusals, attempted commands, and tool failures in that
turn are visible to the judge.

The model call runs in a detached background process, so the reply is never
held up. Runners are tried in `llm-judge` order: `codex` (gpt-5.3-codex-spark),
then `claude` (haiku, hooks off), then `cursor-agent`, first answer wins.

The verdict reports one turn later. On the next prompt the `llm-judge` inbox
shows a hit as the dictionary's `on_hit` text. If no runner could answer, or
the result could not be checked, the inbox says "could not judge" instead of
staying quiet. A clean verdict shows nothing.

`llm-judge` is loaded from the sibling folder (`../llm-judge/judge.py`), which
sits next to this one in the repo and in each harness's `hooks/` folder. If it
cannot be loaded, or the enqueue path raises unexpectedly, the hook writes
`catstack-hook-error handback-needs-attempt: <error>` to stderr and its exit
status and output stay the same.

To grow coverage, add the real text of any miss to the dictionary's `match`
phrases, or the real text of any false alarm to `not_match`. Do not add a
pattern to this hook; the prose meaning belongs in the phrase dictionary.

## Files

- `detect.py` - judge enqueue + once-per-reply state
- `claude_stop_check.py` - Claude `Stop` (stderr advisory)
- `install_claude_hook.py`

## Install

`./install.sh` from the repo root. Restart the harness.

## Tests

```sh
python3 -m unittest discover -s engine/hooks/handback-needs-attempt/tests -v
python3 scripts/check_hook_test_coverage.py
```
