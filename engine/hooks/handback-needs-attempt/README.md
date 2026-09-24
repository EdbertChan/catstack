# handback-needs-attempt

When the assistant tells the user to run a command or perform a step that the
agent could have attempted first, report the hand-back on a later turn.

The hook does not decide that from local wording rules. On every Stop it reads
the current turn's transcript rows, combines the last assistant reply with the
turn's tool calls and results, and hands that exchange to the background judge
using
[`engine/hooks/llm-judge/phrases/handback-needs-attempt.json`](../llm-judge/phrases/handback-needs-attempt.json).
A hit arrives on a later turn through the shared [`llm-judge`](../llm-judge/README.md)
inbox and carries the dictionary's `on_hit` text. The live reply is never held
up. If the judge result was unchecked, the inbox reports "could not judge"
instead of treating the reply as clean. Fail-open.

It fires on replies like "Please run: invoker-cli setup slack ... then tell me
when it completes" or "Simulator build still passes. Now on your end in
Xcode:" when the current turn does not show an attempt first.

It stays silent after a typed permission denial, sandbox refusal, classifier
refusal, or other explicit tool refusal in the current turn. It also stays
silent for steps only the human can do, such as entering a password,
completing OAuth consent, approving hardware access, or clicking a human-only
approval dialog. The escape hatch is to name the typed refusal or human-only
blocker in the reply.

## Model-judged path

`enqueue_judge` in `detect.py` checks the enforcement flag, reads the
transcript, scopes the exchange to the person's current turn, and sends a
phrase-dictionary job to `llm-judge`. The dictionary defines the meaning with
`match` and `not_match` examples and supplies this hit text:

```text
handback-needs-attempt: this reply hands the user a step the agent did not attempt. Attempt the command first, or state the typed refusal or human-only blocker that makes it unavailable.
```

No job is sent when `stop_hook_active` is set, when the reply is empty, when
the payload has no transcript path, or when the current turn contains a typed
refusal marker. Harness and tool-result rows do not count as the person
speaking when the turn is scoped.

The model call runs in a detached background process, so the reply is never
held up. The verdict reports one turn later. On the next prompt the
`llm-judge` inbox shows a hit as the dictionary's `on_hit` text. If no runner
could answer, or the result could not be checked, the inbox says "could not
judge" instead of staying quiet. A clean verdict shows nothing.

Unreadable local input also fails open. A malformed Stop payload or unreadable
transcript prints `catstack-hook-unchecked handback-needs-attempt: ...` to
stderr and does not block the reply.

To grow coverage, add the real text of any miss to the dictionary's `match`
phrases, or the real text of any false alarm to `not_match`. Do not add a
pattern to this hook; the prose meaning belongs in the phrase dictionary.

## Files

- `detect.py` - judge enqueue and current-turn exchange construction
- `claude_stop_check.py` - Claude `Stop` entrypoint
- `install_claude_hook.py` - Claude settings merge
- `claude.hook.json` - Stop hook manifest

## Install

`./install.sh` from the repo root. Restart the harness.

## Tests

```sh
python3 -m unittest discover -s engine/hooks/handback-needs-attempt/tests -v
python3 scripts/ci/check_hook_test_coverage.py engine/hooks/handback-needs-attempt
```

## Off unless you opt in

This hook uses the shared enforcement gate and does nothing unless
`CATSTACK_REFLECT_ENFORCEMENT` is on:

```sh
echo 'CATSTACK_REFLECT_ENFORCEMENT=1' >> ~/.catstack.env
```

The environment, `$CATSTACK_ENV_FILE`, the repo's `.env` and `~/.catstack.env`
are all consulted, in that order. See `engine/hooks/_flags/README.md`.
