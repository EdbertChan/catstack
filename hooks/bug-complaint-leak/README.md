# bug-complaint-leak

When the user files a bug complaint, inject a how-we-got-here + leak checklist
before the agent plans a fix. When workspace Grep of user-quoted product copy
comes up empty twice, require `git grep origin/master` / `git log -S` before
more local Grep.

Fail-open. Inject-only on prompt submit (does not run git). Does not vendor
`skills/reflect/` into Invoker. Does not fire on ordinary implement prompts
like "add a comment to Foo.ts".

## Files

- `detect.py` — bug-complaint matching + checklist text
- `state.py` — session cache for empty/repeat Grep
- `claude_prompt_submit.py` — Claude `UserPromptSubmit` inject
- `claude_pretooluse_grep.py` / `claude_posttooluse.py` — Grep leak gate
- `cursor_before_submit.py` / `cursor_post_tool_use.py` — Cursor parity
  (`beforeSubmitPrompt` cannot inject context; checklist arrives on first
  `postToolUse` via `additional_context`)
- `install_claude_hook.py` / `install_cursor_hook.py` — merge, do not overwrite

## Install

```sh
ln -sfn "$(pwd)/hooks/bug-complaint-leak" ~/.claude/hooks/bug-complaint-leak
mkdir -p ~/.cursor/hooks
ln -sfn "$(pwd)/hooks/bug-complaint-leak" ~/.cursor/hooks/bug-complaint-leak
python3 hooks/bug-complaint-leak/install_claude_hook.py
python3 hooks/bug-complaint-leak/install_cursor_hook.py
```

Or rerun catstack `./install.sh` after it gains these steps.

## Tests

```sh
python3 -m unittest discover -s hooks/bug-complaint-leak/tests -v
```
