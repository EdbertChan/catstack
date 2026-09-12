# split-scope

Inject the existing `split-scope` skill when the user's prompt plans
multi-slice or multi-PR work.

Fail-open. Inject-only. Never blocks a tool. Stays silent on single-file
edits, typo fixes, and questions that only mention `split-scope` by name.

## Fires On

- `pr stack`, `stack of prs`, `stacked prs`
- `multiple prs`, `several prs`, `multi-pr`
- `split this into`, `break this into prs`, `into slices`
- `migration plan`, `plan a migration`, `plan the migration`

## Reminder

`split-scope: this prompt plans multi-slice work. Before writing the plan or PR stack, read the split-scope skill (product/skills/split-scope/SKILL.md, or the installed split-scope skill) and give each slice one review claim with a user-confirmed safety invariant.`

## Fail Direction

Unreadable hook input, detector exceptions, and state read or write failures
are allowed. Entrypoints log the failing entrypoint context to stderr and exit
0 without stdout when an exception reaches the wrapper.

## Files

- `detect.py` - prompt regex detector
- `state.py` - Cursor pending-prompt state under `~/.cache/catstack-split-scope`
- `claude_prompt_submit.py` - Claude `UserPromptSubmit` injection
- `codex_prompt_submit.py` - Codex `UserPromptSubmit` injection
- `cursor_before_submit.py` / `cursor_post_tool_use.py` - Cursor delayed
  delivery because `beforeSubmitPrompt` cannot inject context
- `install_claude_hook.py` / `install_cursor_hook.py` / `install_codex_hook.py`

## Install

`./install.sh` from the catstack repo root, then restart Claude Code, Cursor,
and Codex. Codex also needs `/hooks` trust.

## Tests

```sh
python3 -m unittest discover -s engine/hooks/split-scope/tests -v
python3 scripts/check_hook_test_coverage.py engine/hooks/split-scope
```
