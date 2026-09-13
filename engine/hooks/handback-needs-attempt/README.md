# handback-needs-attempt

On Claude `Stop`, flag a reply that hands the user a command or actionable
step the agent could have attempted when the current turn has no attempt before
the hand-back.

This is the mechanical backstop for cat-mode's rule that a hand-back is an
unverified claim. The hook does not decide that from local wording rules. On
every Stop it hands the latest reply and turn exchange to the background judge
using
[`engine/hooks/llm-judge/phrases/handback-needs-attempt.json`](../llm-judge/phrases/handback-needs-attempt.json).
A hit arrives on a later turn through the shared [`llm-judge`](../llm-judge/README.md)
inbox and carries the dictionary's `on_hit` text. The live reply is never held
up. If the judge result was unchecked, the inbox reports "could not judge"
instead of treating the reply as clean. Fail-open.

Stay silent after a permission denial, sandbox refusal, classifier refusal, or a
step that only the human can do, such as entering a password, granting OAuth
consent, approving a hardware prompt, or connecting hardware. Quoted or
documented instructions are not hand-backs.

When prompted, attempt the command or step first and report the result. If it
truly requires the human, name the permission denial, sandbox or classifier
refusal, password, OAuth consent, or hardware requirement that makes it
human-only. `stop_hook_active` is a one-rewrite escape hatch.

## Model-judged path

`enqueue_judge` in `detect.py` reads the transcript, takes the current reply,
builds a phrase-dictionary job from the latest exchange, and sends it to
`llm-judge`. The dictionary defines the meaning with `match` and `not_match`
examples and supplies the static `on_hit` follow-up text.

No job is sent when `stop_hook_active` is set, when this transcript or reply was
already prompted, or when the reply is empty. Inside a judge run
(`CATSTACK_LLM_JUDGE_CHILD=1`) `llm-judge` refuses the job.

The model call runs in a detached background process, so the reply is never held
up. Runners are tried in `llm-judge` order: `codex` (gpt-5.3-codex-spark), then
`claude` (haiku, hooks off), then `cursor-agent`, first answer wins.

The verdict reports one turn later. On the next prompt the `llm-judge` inbox
shows a hit as the dictionary's `on_hit` text. If no runner could answer, or the
result could not be checked, the inbox says "could not judge" instead of staying
quiet. A clean verdict shows nothing.

`llm-judge` is loaded from the sibling folder (`../llm-judge/judge.py`), which
sits next to this one in the repo and in each harness's `hooks/` folder. If the
hook input is malformed JSON, the wrapper returns quietly. If judge enqueue
raises, the hook writes `catstack-hook-error handback-needs-attempt: <error>` to
stderr and otherwise stays fail-open.

To grow coverage, add the real text of any miss to the dictionary's `match`
phrases, or the real text of any false alarm to `not_match`. Do not add a
pattern to this hook; the prose meaning belongs in the phrase dictionary.

## Files

- `detect.py` - judge enqueue + once-per-transcript state
- `claude_stop_check.py` - Claude `Stop` wrapper
- `claude.hook.json` - Claude hook fragment
- `install_claude_hook.py` - idempotent Claude settings merge
- `tests/` - positive, exception, fail-open, install, and unchecked outcomes
- `../llm-judge/phrases/handback-needs-attempt.json` - phrase dictionary

## Install

`./install.sh` from the repo root. Restart the harness.

## Tests

```sh
python3 -m unittest discover -s engine/hooks/handback-needs-attempt/tests -v
python3 scripts/check_hook_test_coverage.py engine/hooks/handback-needs-attempt
```
