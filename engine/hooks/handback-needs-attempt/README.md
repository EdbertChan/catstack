# handback-needs-attempt

When the assistant asks the user to run a command, open a tool, or do a
local step that the agent could have attempted in the same turn, send a
follow-up telling the agent to try the step first or name why only the user
can do it.

The hook does not decide that from local wording rules. On every Stop it hands
the last assistant reply, the turn's tool calls, and the tool results to the
background judge using `engine/hooks/llm-judge/phrases/handback-needs-attempt.json`.
A hit arrives on a later turn through the shared `llm-judge` inbox and carries
the dictionary's `on_hit` text. The live reply is never held up. If the judge
result was unchecked, the inbox reports "could not judge" instead of treating
the reply as clean. Fail-open.

Silent when the transcript shows the agent attempted the named command or step
this turn. Silent after a permission denial, a sandbox refusal, a classifier
refusal, or a tool refusal. Silent when the step is something only a human can
do, such as entering a password, granting OAuth consent, using local hardware,
or taking an action in a private account UI the agent cannot access.

Not a generic "please run" rule. Quoted examples, fenced instructions, and
descriptions of the policy belong in the phrase dictionary's `not_match`
examples, not in hook-local patterns.

## Model-judged path

`enqueue_judge` in `detect.py` reads the transcript, takes the current reply,
collects the turn's tool calls and results, builds a phrase-dictionary job, and
sends it to `llm-judge`. The dictionary defines the meaning with `match` and
`not_match` examples and supplies the static `on_hit` follow-up text.

No job is sent when `stop_hook_active` is set, when the reply is empty, or when
the transcript cannot be read. All enqueue errors fail open.

The model call runs in a detached background process, so the reply is never
held up. Runners are tried in `llm-judge` order: `codex`, then `claude`, then
`cursor-agent`, first answer wins.

The verdict reports one turn later. On the next prompt the `llm-judge` inbox
shows a hit as the dictionary's `on_hit` text. If no runner could answer, or
the result could not be checked, the inbox says "could not judge" instead of
staying quiet. A clean verdict shows nothing.

To grow coverage, add the real text of any miss to the dictionary's `match`
phrases, or the real text of any false alarm to `not_match`. Do not add a
pattern to this hook; the prose meaning belongs in the phrase dictionary.

## Files

- `detect.py` - judge enqueue and transcript extraction
- `claude_stop_check.py` - Claude `Stop` entrypoint
- `claude.hook.json`
- `install_claude_hook.py`
- `tests/test_hooks.py`

## Install

`./install.sh` from the repo root. Restart the harness.

## Tests

```sh
python3 -m unittest discover -s engine/hooks/handback-needs-attempt/tests -v
python3 scripts/check_hook_test_coverage.py engine/hooks/handback-needs-attempt
```
