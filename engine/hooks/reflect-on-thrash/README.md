# reflect-on-thrash

When `token_audit.py` flags real thrash (stuck retries, edits with no check,
user frustration, or 3+ identical re-reads), **defer** a reflect prompt. Do
not steal the current turn.

**Exception:** `intervention-must-automate` (same-type complaint, verbatim
re-send, "you fucked up/messed up" aimed at the agent) injects immediately:
Claude Stop exit 2, Cursor `followup_message`. That prompt runs reflect
**and** automate-me. Do not wait for session end or for the user to re-prompt.

Cursor `stop` and Claude `Stop` write a deferred marker for ordinary thrash.
Cursor `sessionEnd` delivers that leftover prompt once. Fail-open.

Not every session. Not a cheaper-model suggestion. Not a single accidental
re-read. One "I told you" defers; the same class twice forces the prompt.

## Files

- `detect.py` — shared gate, deferred vs prompted markers, transcript lookup
- `claude_stop_reflect.py` — Claude `Stop` (defer ordinary thrash; exit 2 on intervention)
- `cursor_session.py` — Cursor `stop` (silent unless intervention) + `sessionEnd` (`followup_message`)
- `install_claude_hook.py` / `install_cursor_hook.py` — merge, do not overwrite

## Install

`./install.sh` from the repo root. Restart the harness.

## Tests

```sh
python3 -m unittest discover -s hooks/reflect-on-thrash/tests -v
```
