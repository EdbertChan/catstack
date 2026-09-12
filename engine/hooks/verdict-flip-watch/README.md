# verdict-flip-watch

Third and last layer of the self-correction guard. Advisory Stop hook.

A verifier that printed `ok` earlier in the session and failed later means any
status reported off the earlier run is stale — as a matter of record, not
interpretation. This hook reads the transcript's own Bash commands and their
`tool_result` output, pairs them, and notes the first target whose verdict
flipped from pass to fail. It stays silent when the outgoing message already
mentions it (`wrong`, `vacuous`, `stale`, `retract`, `now fails`, …).

## Why a third layer

The two layers above it both depend on the model:

1. `wrong-check-reflect` matches the shape of a retraction in the outgoing
   text — so it only helps once the model has decided to admit something.
2. `principle-flag-your-own-corrections` carries the judgment no regex can
   enumerate — but still needs the model to notice the claim went stale.

This hook needs neither. It catches the silent switch to the corrected value,
which is the failure `principle-flag-your-own-corrections` names: the user
cannot tell a silent correction from consistency.

The live case it was written for: `check_skill_test_coverage.py` printed `ok`
for a stacked slice it never compared, that result was reported as "fully
green", and the same script failed once it was given the slice refs. Nothing
mechanical connected the two runs.

## Scope

Only verifier-shaped commands count — `check_*`, `test_*`, `run_*`, pytest,
unittest, npm/pnpm test, cargo/go test, make test/check, jest, vitest,
preflight. Tracking every `ls` would make a flip meaningless.

`fail` wins over `pass` when both appear in one output, because a run can
print `ok` lines for early gates and still fail overall.

Advisory on purpose: exit 0, stderr. A gate can legitimately start failing
because the turn broke it deliberately, and the hook cannot know intent. Once
per transcript per target. Fail-open on any parse or IO error.

## Files

- `detect.py` — command/result pairing, verdict classification, `decide()`
- `claude_stop_check.py` — Claude `Stop` entrypoint (stderr, exit 0)
- `claude.hook.json` / `install_claude_hook.py` — settings.json merge (idempotent)
- `tests/fixtures/` — transcripts that fire and stay silent
- `tests/test_hooks.py`

## Install

`./install.sh` from the repo root. Restart the harness.

## Tests

```sh
python3 -m unittest discover -s engine/hooks/verdict-flip-watch/tests -v
python3 scripts/check_hook_test_coverage.py engine/hooks/verdict-flip-watch
```

## Off unless you opt in

This hook is part of the reflect/automate-me class and does nothing unless
`CATSTACK_REFLECT_ENFORCEMENT` is on:

```sh
echo 'CATSTACK_REFLECT_ENFORCEMENT=1' >> ~/.catstack.env
```

The environment, `$CATSTACK_ENV_FILE`, the repo's `.env` and `~/.catstack.env`
are all consulted, in that order. See `engine/hooks/_flags/README.md`.

It belongs to this class because its message ends in "the admission is a
reflect trigger".
