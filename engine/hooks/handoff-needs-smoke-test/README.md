# handoff-needs-smoke-test

Stop hook: a script handed to the user is a claim that it runs.

Fires when the outgoing reply asks the user to execute a script — `! bash
<path>` on its own line, or the same form inside inline code — and this
session's transcript shows no Bash call that ran that path through an
interpreter. Writing the file, `chmod`, `scp`, and `cat` do not count;
`bash <path>`, `sh`, `zsh`, `python3`, `node`, and `source` do.

Silent on: a handoff whose script this session already ran; a reply that
names why the run cannot happen here ("cannot run it here: the sign-in
needs your browser", "only you can approve it"); a command shown for
reference without the `!` handoff form; a one-off `gh` or `git` command
that is not a script path.

Block message names the unrun script and the two ways out: run it end to
end, or run the same transport with a harmless payload first. The escape is
naming the blocker, not omitting it.

## Fail direction

Fails open on every read it cannot complete: no `transcript_path`, an
unreadable or malformed transcript, or any detector error. A Stop hook that
cannot see the transcript cannot tell a tested handoff from an untested
one, and blocking every reply on an unreadable file would wedge the
session. `stop_hook_active` also returns early so the rewritten turn can
finish.

## Files

- `detect.py` — handoff shapes, the blocker vocabulary, transcript scan, `decide()`.
- `claude_stop_check.py` — Claude Stop entrypoint.
- `claude.hook.json` / `install_claude_hook.py` — settings.json merge (idempotent).
- `tests/fixtures/handoffs_{fires,silent}.json` — the verbatim reply that
  motivated this, plus its near-neighbours.
- `tests/test_hooks.py`
