# scratchpad-collision

PreToolUse hook on Write / Edit / MultiEdit / NotebookEdit / Bash: two
agents must not share one scratchpad file name. Every agent in a session
(the parent and each subagent) is handed the same scratchpad directory
(`/private/tmp/claude-*/**/scratchpad/` or `$CLAUDE_SCRATCHPAD`). Before a
write into it (a tool `file_path`, or a Bash `>` / `>>` / `tee` / `cp` /
`mv` target), the hook checks who wrote that file last (a `.writers.json`
sidecar it keeps in the scratchpad dir, keyed by absolute path; the writer
is the hook input's `agent_id`, else the transcript file name, else the
session id) and how long ago (the file's mtime). A different writer within
ten minutes blocks (exit 2) with "another agent wrote pr-body.md 30 s ago;
use a uniquely named file". The same writer, an unknown writer, an older
file, or a new file records the current writer and passes.

The incident: two agents in one session both wrote `pr-body.md`, and PR #8
was published with PR #7's body.

Fail-open on any read, parse, or sidecar error.

## Files

- `detect.py` -- scratchpad path match, target extraction, sidecar, `decide()`.
- `claude_pretooluse.py` -- Claude PreToolUse entrypoint.
- `claude.hook.json` / `install_claude_hook.py` -- settings.json merge (idempotent).
- `tests/test_hooks.py` -- the two-agent `pr-body.md` collision (blocked),
  same writer, unique name, expired window, unknown writer, non-scratchpad
  paths (allowed).

Tests: `python3 -m unittest discover -s engine/hooks/scratchpad-collision/tests -v`
