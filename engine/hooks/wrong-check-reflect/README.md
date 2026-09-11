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
