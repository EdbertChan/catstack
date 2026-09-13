# unverified-tag-check

Check every well-formed `CAT-UNVERIFIED` tag in the background and report
whether the blocker held.

The hook fires on a finished assistant reply from Claude `Stop`, Cursor
`stop`, and Codex `notify` (`agent-turn-complete`). It looks for a tag shaped
like:

```text
{{CAT-UNVERIFIED: <claim> -- cannot verify: <blocker>}}
```

Malformed tags stay silent. Tags inside closed code fences or inline code stay
silent. A claim already checked in the same transcript within 2 hours stays
silent. Anything after the first 3 tags in one reply is ignored.

The live reply is never blocked or delayed. The hook hands one read-only
investigation job to [`llm-judge`](../llm-judge/README.md) for each new tag and
returns.

On the next step, the shared `llm-judge` inbox shows the job's `on_hit` text
and the checker's report sentence:

```text
unverified-tag-check: checked "<claim clipped to 120 chars>". Tell the user this result in plain words: <report>
```

The checker reports whether the stated blocker was real and whether the claim
is true, false, or unknown from readable evidence. It only gets Read, Grep, and
Glob, so it cannot run shell or network checks. If local files and transcripts
cannot answer the question, it says unknown.

Fail-open. An unreadable reply, missing transcript, broken judge, broken state,
or missing runner hands off nothing or comes back unchecked. It never becomes a
true result, and it never blocks the reply.

## Files

- `detect.py` - tag extraction, two-hour state, and `llm-judge` job enqueue
- `claude_stop_check.py` - Claude `Stop`
- `cursor_session.py` - Cursor `stop` / `sessionEnd`
- `codex_notify.py` - Codex `notify`
- `install_claude_hook.py` / `install_cursor_hook.py` / `install_codex_notify.py`

## Install

`./install.sh` from the repo root. Restart the harness.

## Tests

```sh
python3 -m unittest discover -s engine/hooks/unverified-tag-check/tests -v
```
