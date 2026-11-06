# artifact-watch-rearm

When someone comments on a published Claude artifact and sends it to Claude, only a session
that holds a live watch with auto-replies armed is woken. Watches are session-local, so a
restart, resume, clear or compaction can drop them and nothing re-arms them. This hook
reminds the agent to re-arm them.

A hook cannot call tools, so it adds one short instruction to the context. It fires on
`SessionStart` (startup, resume, clear, compact) and `UserPromptSubmit`. It reads
`transcript_path`, finds every `claude.ai/artifact/<id>` this session published or the user
typed, and tells the agent to list its watches (`ArtifactComments` action `watch`, no url) and
re-run `watch` with `replies true` for any that are missing.

## What counts as an artifact to re-arm

- A successful `Artifact` publish whose result reads `Published ... at <url>`.
- A URL the user typed in their own message (system-reminder text is ignored).
- A read whose header says `owned by you` or `writer` counts as editable.
- Left out: an artifact whose `read` header says neither (view only), and one the session
  stopped with `watch` and `on: false` (until a later publish or user mention).

Silent when the transcript has no such URL.

## Once per session

`SessionStart` always injects when there is a candidate: a restart is exactly when the watch is
lost. `UserPromptSubmit` injects only when its set of artifacts has not been injected since the
last `SessionStart`, so it catches a new artifact without nagging every prompt. State lives in
`$ARTIFACT_WATCH_REARM_STATE_DIR` (default `~/.cache/catstack-artifact-watch-rearm`).

## Failing loudly

An unreadable transcript line, a non-object row, an unreadable transcript file, or a missing
`transcript_path` is written to stderr with the path and line number, and the count is repeated
in a summary line and in the finding's evidence. The hook still answers from the lines it could
read; it never reports those lines as clean.

## Harnesses

Claude only. `ArtifactComments` is a Claude Code tool, so the instruction is meaningless to
Cursor and Codex; `install_from_registry.py` lists the hook in `CLAUDE_ONLY_HOOKS` and links it
for Claude only.

## Files

- `detect.py` -- transcript scan, once-per-session state, `detect()`.
- `claude_rearm.py` -- the one entrypoint wired to both events.
- `claude.hook.json` -- `SessionStart` (`startup|resume|clear|compact`) and `UserPromptSubmit`.
- `tests/test_hooks.py` -- fires, silent, once-per-session, unreadable-line, entrypoint, install.

Tests: `python3 -m unittest discover -s engine/hooks/artifact-watch-rearm/tests -v`
