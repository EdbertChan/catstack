# plan-discipline

Spec only until Agent mode can land the Python. Approved in the 2026-08-24
scoring-audit reflect (Backlog 2–4).

## Must catch

1. **Declined SwitchMode → no product `.py` Write/StrReplace.** Plan mode
   already rolls these back; if a Write still goes out, PreToolUse blocks
   it. Fail-open if the SwitchMode payload shape is unknown.
2. **New-module plans need `## How we test`.** PreToolUse on `*.plan.md`
   when todos/body name a new `.py` module and that heading is missing.
3. **No numeric eval in chat/canvas without a verifying Shell this
   session.** Stop/follow-up if the outgoing text has `recall@` or similar
   and `shell_count` is 0.
4. **Semantic plan-churn warning, not a block.** Same plan path rewritten
   with a different overview: tell the user the pivot. Exact-repeat Reads
   of the plan file are not this catch.

## Files to add in Agent mode

- `state.py` — session-local: `switchmode_declined`, `shell_count`, last
  plan overview by path
- `detect.py` — pure functions (product path, how-we-test missing, eval
  number, overview extract)
- `cursor_pretooluse.py` / `cursor_posttooluse.py` / `cursor_stop.py`
- Claude equivalents if PreToolUse/PostToolUse/Stop exist
- `install_cursor_hook.py` — merge, do not overwrite
- `tests/test_hooks.py`
- `install.sh` + CI unittest discover

Fail-open. No machine-specific paths. Marker strings like other hooks.
