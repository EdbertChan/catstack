# diu-stop

Two enforcement points for the `diu` skill, not one. `claude_stop_check.py`
is reactive: when the agent is about to end its turn, check the final
response's length and push back if it looks long enough to have skipped the
ELI5 rule. `claude_prompt_reminder.py` is proactive: it fires on the first
human prompt of a session and again on the first human prompt after each
context compaction, injecting a short diu reminder as fresh context right
when the rule is otherwise most likely to have fallen out of context. The
Stop hook can't tell a legitimately long answer from a lazy one and only
catches the problem after the words are already written; the prompt-submit
reminder can't force anything, but it means the rule reappears in the
newest part of context exactly when a compaction could have dropped it,
instead of on every single turn. It stays silent for prompts that are not
the human speaking -- task notifications, queued or system-injected input.

The claim check reads only the main agent's turn-final message: of 337 unproven claims found in stored transcripts, 196 were mid-turn or subagent text it never saw. See [`COVERAGE.md`](COVERAGE.md) before reading its silence as clearance.

## What buys a paragraph its silence

A fenced block of output, inline code that looks like output, a well-formed
`{{CAT-UNVERIFIED: ... -- cannot verify: ...}}` tag, or a file citation --
and a citation has to be backed. `path:line` on its own used to silence a
paragraph with no check that the file existed, that anyone read it, or at
what ref; a made-up path silenced the gate exactly as well as a real one. A
citation now counts when it names the ref it was read at (`path:line @
origin/main`, the form `corpus/CLAUDE.learned.md` already asks for in prose),
or when the session's transcript shows a tool call that named that path.

Three outcomes, not two. When the transcript cannot be read, whether the path
was read is *unchecked*: the citation does not buy silence, and the block says
which path it could not check and that the ref would settle it.

Not one file per harness, because there is no single "stop" mechanism
shared by every harness -- each one has a genuinely different amount of
power at that point:

| Harness | Mechanism | Can it force a rewrite? | Verified? |
|---|---|---|---|
| Claude Code | Native `Stop` hook, `type: "command"` (`claude_stop_check.py`) + native `UserPromptSubmit` hook (`claude_prompt_reminder.py`) | `Stop`: yes -- `permissionDecision: "deny"` blocks the stop and the agent must respond again. `UserPromptSubmit`: no, it only injects `additionalContext` before generation -- a nudge, not an enforcement point. | Both confirmed live end to end (see below). The Stop hook's first version used `type: "prompt"` (an LLM judging the response) and was dropped: the judge model repeatedly ignored "output ONLY JSON" and dumped its raw reasoning into the transcript as "Stop hook feedback" -- once even after deciding *allow*. `claude_stop_check.py` replaces that with a plain word-count check, no LLM involved, so it can't malform its own output. Trade-off: it can't tell a legitimately long, requested answer from a lazy one -- pure word count only. Per Claude Code's docs, a deny always shows *something* to the user; there's no full-mute option. |
| Cursor | `stop` hook, `type: "prompt"` | Soft only -- `followup_message` posts one more nudge as if the user said it, capped at 5 automatic loops (`loop_count`/`loop_limit`) | UNVERIFIED end-to-end -- not yet run live in Cursor. Given what happened with Claude Code's prompt-hook, expect the same failure mode here; if it shows up, swap this one for a deterministic script too, same pattern as `claude_stop_check.py`. No `UserPromptSubmit`-equivalent proactive reminder exists for Cursor yet. |
| Codex CLI | `notify` script (`config.toml`) | No -- fires once, after the turn is already over, stdin/stdout closed, no way to block or continue | The JSON-parsing, word-count, and chained-notify logic were all tested locally and work (see below). No proactive reminder mechanism exists for Codex either -- `notify` only fires after a turn ends. |

## Files

- `claude.hook.json` -- the `Stop` hook `"hooks"` object to merge into `~/.claude/settings.json`.
- `claude_stop_check.py` -- the script that hook runs. Its word count and claim checks use no model; it also asks the background judge about the `phrases/` word lists and waits for that answer, so a hit blocks the same turn. No machine-specific paths.
- `claude.prompt.hook.json` -- the `UserPromptSubmit` hook `"hooks"` object, merged the same way.
- `claude_prompt_reminder.py` -- the script that hook runs. No LLM. Emits the same short reminder, gated to once per session and once per compaction, and only for prompts the human actually typed (`events.is_human_prompt`, `events.once_per_session_or_compaction` in `_sdk`).
- `diu_limit.py` -- the word limit and what it does not count. The reminder's wording and the Stop hook's check both read it, so they cannot disagree; `tests/test_limit_agreement.py` pins that.
- `plain_words.py` -- turns every `phrases/` word list into one question about the user's last message and the finished reply, hands it to the background judge, and waits for the answer so a hit blocks the same turn. A verdict delivered on the next prompt is one the user may never see. No answer in time means the turn ends unblocked.
- `phrases/` -- the word lists themselves, one file per kind of wording to avoid, in the format `engine/hooks/llm-judge/phrases.py` loads.
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
$ echo '{"last_assistant_message":"<200 words>"}' | python3 ~/.claude/hooks/diu-stop/claude_stop_check.py
{"hookSpecificOutput": {"hookEventName": "Stop", "permissionDecision": "deny", "permissionDecisionReason": "Apply diu: 200 words, over the 150-word guideline. Rewrite shorter and in plain language, unless this turn genuinely asked for full technical detail or a specific long format."}}
$ echo '{"last_assistant_message":"short reply"}' | python3 ~/.claude/hooks/diu-stop/claude_stop_check.py
(no output)
```

```
$ echo '{"session_id":"test123"}' | python3 ~/.claude/hooks/diu-stop/claude_prompt_reminder.py
{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "diu reminder: lead with the outcome, no preamble or closing pleasantries, ELI5 under 150 words, not counting fenced code blocks or markdown table rows, unless this turn needs technical depth, number multi-step work, cap lists at 5, matter-of-fact tone on errors. Full rules: skills/diu/SKILL.md."}}
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
first place). `claude_prompt_reminder.py` and `install_claude_hook.py`'s
merge of both hook types are covered by `hooks/diu-stop/tests/test_hooks.py`
(45 tests, all passing) plus the live pipe-test above; not yet confirmed
that Claude Code actually surfaces `additionalContext` to the model's
context the way the docs describe -- only that the hook itself emits the
correct payload. Cursor's `stop` hook has not been exercised live yet.
