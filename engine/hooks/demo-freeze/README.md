# demo-freeze

PreToolUse hook (Edit|Write|MultiEdit|NotebookEdit): while `/tmp/.demo-freeze`
exists, edits to any path it lists (absolute path, `dir/` prefix, or glob —
one per line, `#` comments allowed) are blocked with exit 2. The agent writes
the marker when a live-demo window opens (per CLAUDE.md live-demo rules) and
deletes it when the window ends. The marker auto-expires after 2 hours so a
forgotten freeze can't haunt later sessions.

Born from a `/reflect` on a 2026-08-17 session: an unrequested layout edit to
the demo page during the user's live test window corrupted it mid-demo.

Register in `~/.claude/settings.json`:

```json
"PreToolUse": [
  { "matcher": "Edit|Write|MultiEdit|NotebookEdit",
    "hooks": [ { "type": "command", "command": "python3 $HOME/.claude/hooks/demo-freeze/claude_pretooluse_check.py", "timeout": 5 } ] }
]
```

Tests: `python3 -m unittest discover -s hooks/demo-freeze/tests -v`
Fail-open: no marker, stale marker, or parse errors always allow the edit.
