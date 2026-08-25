# restart-risk-check

When the assistant's own message asserts a remote-host restart is
low-risk/safe, require evidence of at least two distinct checks that turn:
a workflow/task queue check AND a concurrent-login/session check (e.g.
`who`/`last`). One signal alone is not enough on a shared host.

Found via `/reflect` on an Invoker session (2026-08-22): the agent said
"restart risk is low" for a DigitalOcean droplet after checking only the
workflow queue, while a same-day hotfix backup file it had already seen on
that host went unconnected. No restart happened that time — the gap was
caught before acting — but the pattern was real.

Fail-open on any read/parse error, and only fires when the message text
actually contains restart-safety language about a remote/SSH host.

## Files

- `detect.py` — claim detection + same-turn Bash command scan
- `claude_stop_restart_check.py` — Claude `Stop` (stderr + exit 2)
- `install_claude_hook.py` — merge, do not overwrite
- `claude.hook.json` — the Stop-hook fragment merged into settings.json

## Install

`./install.sh` from the repo root (or run `install_claude_hook.py`
directly). Restart the harness, or open `/hooks` once to reload.

## Tests

```sh
python3 -m unittest discover -s hooks/restart-risk-check/tests -v
```
