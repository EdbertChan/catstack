# remote-payload-collapses

PreToolUse hook (Bash): `sudo -i` re-parses the command you already quoted.

`sudo -i` starts the target user's login shell, and that shell parses the
remaining arguments a second time. Quoting consumed by the first parse is
gone by then, so a quoted command string is re-split on whitespace and its
first word becomes the whole command.

Reproduced on a real host, one variable apart:

```
ssh host 'sudo -u demo -H    bash -lc '"'"'set -u<newline>echo one'"'"''
  -> one

ssh host 'sudo -u demo -H -i bash -lc '"'"'set -u<newline>echo one'"'"''
  -> bash: line 1: set: -c: invalid option
```

Fires when a command passes a quoted command string through `sudo … -i`,
`su -`, or `su -l`. Silent on: the same line without `-i`; a script copied
to the host and run by path; a multi-line body handed straight to `ssh`
with no login shell; a heredoc piped to a remote `bash -s` on stdin; an
interactive `sudo -i` with no command; a local `python3 -c` after a pipe.

Newlines are not the trigger. A multi-line body survives `ssh` and survives
`sudo` without `-i`; the second parse is what breaks it, on one line or
many.

## Fail direction

Blocks (exit 2). The shape is decidable from the command text alone, with
no probe and no file read, so there is no unreadable-input case to fail
open on. A detector error is caught and allows the call.

Backtested over 37,015 real Bash commands: 6 hits, all the broken shape.

## Files

- `detect.py` — login-shell patterns, heredoc stripping, `collapse_risk()`.
- `claude_pretooluse_check.py` — Claude PreToolUse entrypoint.
- `claude.hook.json` / `install_claude_hook.py` — settings.json merge (idempotent).
- `tests/fixtures/commands_{fire,silent}.json` — the incident and its neighbours.
- `tests/test_hooks.py`
