# cat-mode-default

Claude Code `UserPromptSubmit` hook. When the flag is on and the prompt is
an investigation or execution, it injects one line of context telling the
model to read and apply the installed `cat-mode` skill for that turn.

`cat-mode` ships with `disable-model-invocation: true`, so on its own it
applies when typed as `/cat-mode`. This hook makes it the default for
work turns without flipping that frontmatter flag.

## Turning it on

Set `CATSTACK_CAT_MODE_DEFAULT=1`. The hook reads it from the process
environment first. If it is not set there, it searches `.env` files in this
order and the first file that defines the key wins:

1. the file named by `$CATSTACK_ENV_FILE`, if that variable is set
2. `<repo root>/.env` for the repo containing the session's `cwd`
3. `~/.catstack.env`

For "on in every repo", add this line to `~/.catstack.env`:

```
CATSTACK_CAT_MODE_DEFAULT=1
```

Files are parsed as plain `KEY=VALUE` lines (`export` prefix and quotes are
tolerated). They are never sourced, and no other key is read or printed.
`0`, `false`, `no`, `off`, or an absent key means off.

## When it fires

Prompt is treated as work when it is longer than a short phrase or carries a
work verb (why, how, fix, build, run, land, make, investigate, check, debug,
...). It stays silent for a bare slash command (`/clear`), a one-word
acknowledgement (`ok`, `thanks`), or any prompt that already contains
`/cat-mode`, so the skill is not applied twice in one turn.

Injected text names the installed file (`~/.claude/skills/cat-mode/SKILL.md`)
so the model reads the real skill. If that file is missing the line says
`cat-mode not installed: run install.sh` instead.

## Files

- `detect.py`: flag resolution, prompt classification, context text.
- `claude_prompt_submit.py`: the Claude entrypoint; fail-open, never denies.
- `claude.prompt.hook.json`: settings fragment `install_claude_hook.py` merges.
- `tests/fixtures/*.json`: one scenario each (fires / silent) with the
  environment, optional `.env` content, and payload.

Related but different: `CAT_MODE_AUTO_INVOKE=true` in catstack's own `.env`
makes `install.sh` materialize a cat-mode copy with model invocation enabled,
which leaves the choice to the model each turn. This hook is deterministic:
flag on plus a work prompt means the context is injected.
