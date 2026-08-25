# frustration-watchdog

Stop hook: when the user's last message was impatience-shaped (all-caps,
profanity, "i told you", "i am waiting", `???`, or a verbatim re-send within
10 minutes), the outgoing assistant message must visibly end the wait — one
concrete user action, a direct question, or an explicit no-action ETA.
Otherwise the turn is blocked (exit 2) with guidance.

Born from a `/reflect` on a 2026-08-17 live-demo session (13/56 user messages
frustration-flagged; the worst followed turns of invisible background work).
Signal patterns mirror `skills/reflect/scripts/token_audit.py` — keep in sync.

Register in `~/.claude/settings.json` under `hooks.Stop[0].hooks`:

```json
{ "type": "command", "command": "python3 $HOME/.claude/hooks/frustration-watchdog/claude_stop_check.py", "timeout": 10 }
```

Tests: `python3 -m unittest discover -s hooks/frustration-watchdog/tests -v`
Fail-open: parse/read errors and `stop_hook_active` always allow the turn.
