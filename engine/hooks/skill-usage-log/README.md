# skill-usage-log

PreToolUse hook (`Skill`): appends one JSON line per Skill tool call to a
local log file, so "which skills are actually used" can eventually be
answered with data instead of guessed from `git log` / last-modified dates.
Off by default -- catstack had no invocation-tracking mechanism at all
before this hook (confirmed by a repo-wide search: no hook matched the
`Skill` tool, no telemetry SDK, nothing in `scripts/` or the reflect
tooling counted per-skill firings).

Enable with:

```sh
export CATSTACK_SKILL_USAGE_LOG=1
```

Log location: `~/.cache/catstack-skill-usage-log/skill-usage.jsonl`
(override the directory with `CATSTACK_SKILL_USAGE_LOG_STATE_DIR`). Each
line: `{"ts": <unix-epoch-seconds>, "skill": "<name>", "args": "<string or
null>", "session_id": "<string or null>", "cwd": "<string or null>"}`.

This is intentionally crude: a local append-only file, no rotation, no
aggregation, no query tool. It exists to draw the architectural boundary
first -- one write function, `record_skill_usage()` in
`claude_pretooluse_log.py` -- so a later swap to a real metrics ingester
(PostHog or otherwise) is a change to that one function, not a rewrite of
the hook.

Claude-only: the `Skill` tool is a Claude Code concept, so this hook is not
linked into Cursor or Codex hook directories.

Register in `~/.claude/settings.json`:

```json
"PreToolUse": [
  { "matcher": "Skill",
    "hooks": [ { "type": "command", "command": "python3 $HOME/.claude/hooks/skill-usage-log/claude_pretooluse_log.py", "timeout": 5 } ] }
]
```

Tests: `python3 -m unittest discover -s engine/hooks/skill-usage-log/tests -v`
Fail-open: env var unset, malformed stdin, non-dict payload, missing skill
name, or an unwritable log directory all leave the Skill call unaffected.
