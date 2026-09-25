# cat-mode-default

Claude Code `UserPromptSubmit` hook. When the flag is on, it injects one line
of context telling the model to read and apply the installed `cat-mode` skill
for that turn.

`cat-mode` ships with `disable-model-invocation: true`, so on its own it
applies when typed as `/cat-mode`. This hook makes it the default for every
prompt without flipping that frontmatter flag.

## Turning it on

Set `CATSTACK_CAT_MODE_DEFAULT=on` (`1` also works). The flag has three
settings:

| Value | What happens |
| --- | --- |
| `off` (or unset, `0`) | `cat-mode` runs only when you type `/cat-mode`. |
| `decide` | This hook stays quiet. `install.sh` installs a copy of `cat-mode` the model may pick on its own each turn. Re-run `install.sh` after switching to or from `decide`. |
| `on` (or `1`) | This hook tells the model to use `cat-mode` on every prompt. |

The hook reads it from the process
environment first. If it is not set there, it searches `.env` files in this
order and the first file that defines the key wins:

1. the file named by `$CATSTACK_ENV_FILE`, if that variable is set
2. `<repo root>/.env` for the repo containing the session's `cwd`
3. `~/.catstack.env`

For "on in every repo", add this line to `~/.catstack.env`:

```
CATSTACK_CAT_MODE_DEFAULT=on
```

Files are parsed as plain `KEY=VALUE` lines (`export` prefix and quotes are
tolerated). They are never sourced, and no other key is read or printed.
Only `on`, `1`, `true`, and `yes` fire this hook; anything else keeps it quiet.

## Stop after answering (opt-in)

`CATSTACK_CAT_MODE_STOP_AFTER_ANSWER=on` adds one more line to what this hook
injects: when a result answers a numbered item from the original ask, the
agent says which item and asks whether to continue before starting more work.
Unset or anything else leaves it off, and the agent keeps taking safe next
steps. It is read from the same places as the main flag, and it does nothing
while `CATSTACK_CAT_MODE_DEFAULT` is off. On a turn where you typed
`/cat-mode`, only this line is injected.

## When it fires

With the flag on, every prompt gets the context unless it already contains a
typed `/cat-mode`, so the skill is not applied twice in one turn. Other slash
commands, acknowledgements, and short execution prompts all get the same
default context.

Injected text names the installed file (`~/.claude/skills/cat-mode/SKILL.md`)
so the model reads the real skill. If that file is missing the line says
`cat-mode not installed: run install.sh` instead.

## Subagents

`UserPromptSubmit` never fires for a subagent: its prompt arrives through
the parent's `Agent` tool call. So the same default rides on a second
entrypoint, `claude_pretooluse_agent.py`, a `PreToolUse` hook matched on
`Agent`. With the flag on it returns `hookSpecificOutput.updatedInput`: the
same `tool_input` with the prompt prefixed by one line,
`cat-mode default is on: read and apply <SKILL.md path> before starting.`
It stays silent when the flag is off or when the prompt already mentions
cat-mode anywhere (a parent that told the subagent to read it gets no
second copy). Same flag resolution as the prompt hook.

The shared registry keeps this hook in `warn` mode. Set
`CATSTACK_HOOK_MODE_CAT_MODE_DEFAULT=off|warn|stop` for a machine-local
override; `stop` turns the `PreToolUse` (Agent) companion into a real block
(exit 2) instead of rewriting the subagent's prompt. Detection or metrics
failures allow the harness action.

## Files

- `detect.py`: flag resolution, typed `/cat-mode` detection, context text,
  and `detect(event)`, the SDK entrypoint returning `Finding` objects.
- `claude_prompt_submit.py` / `claude_pretooluse_agent.py`: thin calls into
  `engine/hooks/_sdk/runtime.py`. The agent finding carries
  `output={"updatedInput": ...}`, which the shared renderer emits as
  `updatedInput` rather than its generic `additionalContext`.
- `claude.prompt.hook.json` / `claude.agent.hook.json`: settings fragments
  `install_claude_hook.py` merges.
- `tests/fixtures/*.json`: one scenario each (fires / silent) with the
  environment, optional `.env` content, and payload.
- `tests/fixtures/agent_*.json`: the same for the Agent-tool companion.

`decide` replaces the retired `CAT_MODE_AUTO_INVOKE=true`. `install.sh` warns
when it still finds that name and ignores it.
