# diu-stop

A stop-time backstop for the `diu` skill: when the agent is about to end its
turn, check the final response's length and push back if it looks long
enough to have skipped the ELI5 rule.

Not one file, because there is no single "stop" mechanism shared by every
harness -- each one has a genuinely different amount of power at that point:

| Harness | Mechanism | Can it force a rewrite? | Verified? |
|---|---|---|---|
| Claude Code | Native `Stop` hook, `type: "command"` | Yes -- `permissionDecision: "deny"` blocks the stop and the agent must respond again | Confirmed live end to end, including the deterministic script version (see below). The first version used `type: "prompt"` (an LLM judging the response) and was dropped: the judge model repeatedly ignored "output ONLY JSON" and dumped its raw reasoning into the transcript as "Stop hook feedback" -- once even after deciding *allow*. `claude_stop_check.py` replaces that with a plain word-count check, no LLM involved, so it can't malform its own output. Trade-off: it can't tell a legitimately long, requested answer from a lazy one -- pure word count only. Per Claude Code's docs, a deny always shows *something* to the user; there's no full-mute option. |
| Cursor | `stop` hook, `type: "prompt"` | Soft only -- `followup_message` posts one more nudge as if the user said it, capped at 5 automatic loops (`loop_count`/`loop_limit`) | UNVERIFIED end-to-end -- not yet run live in Cursor. Given what happened with Claude Code's prompt-hook, expect the same failure mode here; if it shows up, swap this one for a deterministic script too, same pattern as `claude_stop_check.py`. |
| Codex CLI | `notify` script (`config.toml`) | No -- fires once, after the turn is already over, stdin/stdout closed, no way to block or continue | The JSON-parsing, word-count, and chained-notify logic were all tested locally and work (see below). |

## Files

- `claude.hook.json` -- the `"hooks"` object to merge into `~/.claude/settings.json`.
- `claude_stop_check.py` -- the script that hook runs. No LLM, no machine-specific paths.
- `cursor.hooks.json` -- the whole file to install as `~/.cursor/hooks.json`.
- `codex_notify.py` -- the script to point Codex's `notify` at. No machine-specific paths.

None of these files contain an absolute path or a username -- `install.sh`
symlinks this whole directory to a fixed location (`~/.claude/hooks/diu-stop`)
and `claude.hook.json` references it via `$HOME`, so the same checked-in
file works on any machine. `codex_notify.py` takes its chain target as
argv, not a hardcoded constant, for the same reason (Codex's `config.toml`
is per-machine and untracked anyway, but the *script* is tracked).

## Install

### Claude Code

`~/.claude/settings.json` already has other keys (model, theme, plugins...),
so this can't be symlinked -- merge the `Stop` hook into its existing `hooks`
key. Run `./install.sh` first (it symlinks `~/.claude/hooks/diu-stop` here),
then:

```sh
python3 - <<'EOF'
import json, pathlib
p = pathlib.Path.home() / ".claude" / "settings.json"
settings = json.loads(p.read_text())
fragment = json.loads(pathlib.Path("hooks/diu-stop/claude.hook.json").read_text())
settings.setdefault("hooks", {}).setdefault("Stop", []).extend(fragment["hooks"]["Stop"])
p.write_text(json.dumps(settings, indent=2) + "\n")
EOF
```

Restart Claude Code (hooks load at session start) and check `/hooks` shows it.

### Cursor

Nothing was at `~/.cursor/hooks.json` on this machine, so it's a plain symlink:

```sh
ln -s "$(pwd)/hooks/diu-stop/cursor.hooks.json" ~/.cursor/hooks.json
```

If you already have hooks configured there for something else, merge
`cursor.hooks.json`'s `stop` entry into the existing file's `hooks.stop`
array instead of symlinking over it.

### Codex CLI

Point `notify` in `~/.codex/config.toml` at `codex_notify.py`. If you
already had a `notify` command configured, pass it as extra argv *before*
where Codex's JSON payload lands -- Codex always appends its payload as the
last element, so `codex_notify.py` treats everything between the script
path and that last element as "call this instead, with these args, then
append the same payload":

```toml
notify = ["python3", "/path/to/catstack/hooks/diu-stop/codex_notify.py", "/path/to/your-old-notify-binary", "some-arg-it-needs"]
```

With no prior `notify` command, drop the extra args:

```toml
notify = ["python3", "/path/to/catstack/hooks/diu-stop/codex_notify.py"]
```

## What's actually verified right now

```
$ echo '{"last_assistant_message":"<200 words>"}' | python3 ~/.claude/hooks/diu-stop/claude_stop_check.py
{"hookSpecificOutput": {"hookEventName": "Stop", "permissionDecision": "deny", "permissionDecisionReason": "Apply diu: 200 words, over the 150-word guideline. Rewrite shorter and in plain language, unless this turn genuinely asked for full technical detail or a specific long format."}}
$ echo '{"last_assistant_message":"short reply"}' | python3 ~/.claude/hooks/diu-stop/claude_stop_check.py
(no output)
```

```
$ python3 codex_notify.py "<chain-binary>" "turn-ended" '{"type":"agent-turn-complete","last-assistant-message":"<200 words>"}'
diu-stop: last response was 200 words (over the 150-word diu guideline). Codex can't be forced to redo it -- check by hand whether it should have been ELI5.
(chain-binary invoked with: turn-ended <json>, no error)
$ python3 codex_notify.py '{"type":"agent-turn-complete","last-assistant-message":"short reply"}'
(no output)
```

Both `claude.hook.json` and `cursor.hooks.json` are confirmed to be valid
JSON. `claude_stop_check.py` has fired against a real Claude Code Stop
event live (this is how the "prompt"-version's failure was caught in the
first place). Cursor's `stop` hook has not been exercised live yet.
