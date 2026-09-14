# wrong-check-reflect

When the assistant takes back an earlier check or claim, inject a `/reflect`
follow-up on a later turn.

The hook does not decide that from local wording rules. On every Stop it hands
the last assistant reply to the background judge using
[`engine/hooks/llm-judge/phrases/wrong-check-reflect.json`](../llm-judge/phrases/wrong-check-reflect.json).
A hit arrives on a later turn through the shared [`llm-judge`](../llm-judge/README.md)
inbox and carries the dictionary's `on_hit` text. The live reply is never held
up. If the judge result was unchecked, the inbox reports "could not judge"
instead of treating the reply as clean. Finish the live correction first.
Fail-open.

Once per transcript. Skip if the user already said `/reflect`.

Not word-count (`diu-stop`). Not token_audit thrash (`reflect-on-thrash`).
Assistant text only - user messages and fenced code stay silent.

## Model-judged path

`enqueue_judge` in `detect.py` reads the transcript, takes the current reply,
builds a phrase-dictionary job, and sends it to `llm-judge`. The dictionary
defines the meaning with `match` and `not_match` examples and supplies the
static `on_hit` follow-up text.

No job is sent when `stop_hook_active` is set, when this transcript or reply
was already prompted, when the reply is empty, or when the user already asked
for `/reflect`. Inside a judge run (`CATSTACK_LLM_JUDGE_CHILD=1`) `llm-judge`
refuses the job.

The model call runs in a detached background process, so the reply is never
held up. Runners are tried in `llm-judge` order: `codex` (gpt-5.3-codex-spark),
then `claude` (haiku, hooks off), then `cursor-agent`, first answer wins.

The verdict reports one turn later. On the next prompt the `llm-judge` inbox
shows a hit as the dictionary's `on_hit` text. If no runner could answer, or
the result could not be checked, the inbox says "could not judge" instead of
staying quiet. A clean verdict shows nothing.

`llm-judge` is loaded from the sibling folder (`../llm-judge/judge.py`), which
sits next to this one in the repo and in each harness's `hooks/` folder. If it
cannot be loaded, or the transcript cannot be read, the hook writes
`wrong-check-reflect: judge enqueue failed: <error>` to stderr and its exit
status and output stay the same.

To grow coverage, add the real text of any miss to the dictionary's `match`
phrases, or the real text of any false alarm to `not_match`. Do not add a
pattern to this hook; the prose meaning belongs in the phrase dictionary.

## Files

- `detect.py` - judge enqueue + once-per-transcript state
- `claude_stop_check.py` — Claude `Stop` (stderr + exit 2)
- `cursor_session.py` — Cursor `stop` / `sessionEnd` (`followup_message`)
- `codex_notify.py` — Codex `notify` (advisory print + chain)
- `install_claude_hook.py` / `install_cursor_hook.py` / `install_codex_notify.py`

## Install

`./install.sh` from the repo root. Restart the harness.

## Tests

```sh
python3 -m unittest discover -s engine/hooks/wrong-check-reflect/tests -v
python3 scripts/check_hook_test_coverage.py engine/hooks/wrong-check-reflect
```

## Off unless you opt in

This hook is part of the reflect/automate-me class and does nothing unless
`CATSTACK_REFLECT_ENFORCEMENT` is on:

```sh
echo 'CATSTACK_REFLECT_ENFORCEMENT=1' >> ~/.catstack.env
```

The environment, `$CATSTACK_ENV_FILE`, the repo's `.env` and `~/.catstack.env`
are all consulted, in that order. See `engine/hooks/_flags/README.md`.

The gate sits inside `enqueue_judge`, so it covers the Claude Stop hook, the
Codex notify and the Cursor session hook with one check.
