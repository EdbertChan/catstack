# wrong-check-reflect

When the assistant admits a prior check/claim was wrong
("Good catch — my earlier check was wrong", "You're right, I misread the file",
"I incorrectly assumed…", "the file I cited was a duplicate", "My mistake — I
misread it", "I misread the front matter on that skill"), inject a
`/reflect` follow-up.

A reply that opens with a standalone "You're right." (or "You are right —")
counts: it concedes that the user caught something the agent's own checks
did not. "You're right that option B is cheaper" is agreement with a claim
and stays silent. "I misread / misunderstood / mixed up" counts with any
object ("I misread which diff you meant"), not only it/that/the.

A bare "I was wrong" counts, with no named check after it. The retraction
that follows a false claim is often the shortest sentence in the turn, and
requiring it to name the check it retracts let the plainest concession
through. The hypothetical ("if I was wrong about this…"), reported-speech
("the reviewer said I was wrong"), product-blame ("the test was wrong"),
third-person, quote, backtick and fence guards all still hold, so only an
admission asserted in the agent's own voice fires. Finish the live correction first. Fail-open.
Once per transcript. Skip if the user already said `/reflect`.

Not word-count (`diu-stop`). Not token_audit thrash (`reflect-on-thrash`).
Assistant text only — user messages and fenced code stay silent.

## Model-judged path

The regexes keep missing new wordings. So when they stay silent, the hook
also asks a small model, through the shared [`llm-judge`](../llm-judge/README.md):
did the user push back, and did the reply take something back?

`enqueue_judge` in `detect.py` reads the transcript and takes three messages:
the current reply, the user message before it, and the assistant message before
that. Each is cut to its last 4000 characters and put under the labels
`EARLIER ASSISTANT`, `USER` and `ASSISTANT` in a prompt that asks for one line
of JSON: `pushback`, `self_correction`, and a `quote`. It is a hit only when
both `pushback` and `self_correction` are `true`.

No job is sent when `stop_hook_active` is set, when the regex already fired,
when this transcript was already prompted, or when any of the three messages is
missing (for example, on the first user message, or when the payload names no
transcript). Inside a judge run
(`CATSTACK_LLM_JUDGE_CHILD=1`) `llm-judge` refuses the job.

The model call runs in a detached background process, so the reply is never
held up. Runners are tried in `llm-judge` order: `codex` (gpt-5.3-codex-spark),
then `claude` (haiku, hooks off), then `cursor-agent`, first answer wins.

The verdict reports one turn later. On the next prompt the `llm-judge` inbox
shows a hit as the same reflect follow-up, with `model judge` as the match. If
no runner could answer, the inbox says so instead of staying quiet. A clean
verdict shows nothing.

`llm-judge` is loaded from the sibling folder (`../llm-judge/judge.py`), which
sits next to this one in the repo and in each harness's `hooks/` folder. If it
cannot be loaded, or the transcript cannot be read, the hook writes
`wrong-check-reflect: judge enqueue failed: <error>` to stderr and its exit
status and output stay the same.

## Files

- `detect.py` — shared admission regex + once-per-transcript state
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
