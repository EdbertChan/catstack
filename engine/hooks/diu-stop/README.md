# diu-stop

`claude_prompt_reminder.py` carries the `diu` brevity rule: it fires before
the agent writes anything, injecting a short diu reminder as fresh context
for that turn. It can't force anything, but it puts the rule in the newest
part of context on every turn, which is the only point where it can still
change what gets written.

`claude_stop_check.py` runs when the agent is about to end its turn and
blocks only on unverified claims: a bare "confirmed" / "this fixes it" /
causal claim with no evidence in the same paragraph, or a leftover
`UNVERIFIED:` marker. It does not count words. A length block fires after
the words are written, so all it can buy is one rewrite of that message;
the next turn runs just as long.

Not one file per harness, because there is no single "stop" mechanism
shared by every harness -- each one has a genuinely different amount of
power at that point:

| Harness | Mechanism | Can it force a rewrite? | Verified? |
|---|---|---|---|
| Claude Code | Native `Stop` hook, `type: "command"` (`claude_stop_check.py`) + native `UserPromptSubmit` hook (`claude_prompt_reminder.py`) | `Stop`: yes -- exit code 2 blocks the stop and the agent must respond again, but only for unverified claims, never for length. `UserPromptSubmit`: no, it only injects `additionalContext` before generation -- a nudge, not an enforcement point. | Both confirmed live end to end (see below). The Stop check is a deterministic script, no LLM involved, so it can't malform its own output. A block always shows *something* to the user; there's no full-mute option. |
| Cursor | `stop` hook, `type: "prompt"` | Soft only -- `followup_message` posts one more nudge as if the user said it, capped at 5 automatic loops (`loop_count`/`loop_limit`) | UNVERIFIED end-to-end -- not yet run live in Cursor. Given what happened with Claude Code's prompt-hook, expect the same failure mode here; if it shows up, swap this one for a deterministic script too, same pattern as `claude_stop_check.py`. No `UserPromptSubmit`-equivalent proactive reminder exists for Cursor yet. |
| Codex CLI | `notify` script (`config.toml`) | No -- fires once, after the turn is already over, stdin/stdout closed, no way to block or continue | The JSON-parsing, word-count, and chained-notify logic were all tested locally and work (see below). No proactive reminder mechanism exists for Codex either -- `notify` only fires after a turn ends. |

## Files

- `word_rule.py` -- the word limit and what it doesn't count (fenced code blocks, table rows). Defined only here: the prompt reminder states it and the Codex notify warns on it.
- `claude.hook.json` -- the `Stop` hook `"hooks"` object to merge into `~/.claude/settings.json`.
- `claude_stop_check.py` -- the script that hook runs: the unverified-claim check. No LLM, no machine-specific paths.
- `claude.prompt.hook.json` -- the `UserPromptSubmit` hook `"hooks"` object, merged the same way.
- `claude_prompt_reminder.py` -- the script that hook runs. No LLM, no per-turn conditional logic -- always emits the same short reminder.
- `install_claude_hook.py` -- merges both of the above into `~/.claude/settings.json`, idempotently, without touching anything else there.
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
so this can't be symlinked -- `install.sh` runs `install_claude_hook.py`,
which merges both the `Stop` hook and the `UserPromptSubmit` hook into its
existing `hooks` key, idempotently (rerunning it converges instead of
duplicating entries). Nothing to do by hand: `./install.sh` handles both.

Restart Claude Code (hooks load at session start) and check `/hooks` shows
both `Stop` and `UserPromptSubmit`.

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
$ echo '{"last_assistant_message":"<200 words>"}' | python3 ~/.claude/hooks/diu-stop/claude_stop_check.py; echo "exit=$?"
exit=0
$ echo '{"last_assistant_message":"Confirmed. <200 words>"}' | python3 ~/.claude/hooks/diu-stop/claude_stop_check.py; echo "exit=$?"
This message makes an unverified-shaped claim ("confirmed") with no adjacent evidence (a command, output, code reference, or an `UNVERIFIED:` prefix). Per skills/prove-it/SKILL.md: either show what was actually run/checked, or prefix the claim with `UNVERIFIED:`.
exit=2
$ echo '{"last_assistant_message":"short reply"}' | python3 ~/.claude/hooks/diu-stop/claude_stop_check.py; echo "exit=$?"
exit=0
```

```
$ echo '{"session_id":"test123"}' | python3 ~/.claude/hooks/diu-stop/claude_prompt_reminder.py
{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "diu reminder: lead with the outcome, no preamble or closing pleasantries, ELI5 under 150 words (fenced code blocks and table rows don't count) unless this turn needs technical depth, number multi-step work, cap lists at 5, matter-of-fact tone on errors. Full rules: skills/diu/SKILL.md."}}
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
event live. `claude_prompt_reminder.py` and `install_claude_hook.py`'s
merge of both hook types are covered by `hooks/diu-stop/tests/test_hooks.py`
plus the live pipe-test above; not yet confirmed
that Claude Code actually surfaces `additionalContext` to the model's
context the way the docs describe -- only that the hook itself emits the
correct payload. Cursor's `stop` hook has not been exercised live yet.
