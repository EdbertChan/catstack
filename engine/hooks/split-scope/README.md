# split-scope

Inject the existing `split-scope` skill reminder when a prompt plans
multi-slice or multi-PR work. The skill is descriptive, so a hook supplies
the prompt-time nudge before a plan or PR stack is written.

Fail-open. Inject-only. Never blocks tools. Stays silent on single-file
edits, typo fixes, and questions that only mention split-scope by name.

## Fires On

- `pr stack`, `stack of prs`, `stacked prs`
- `multiple prs`, `several prs`, `multi-pr`
- `split this into`, `break this into prs`, `into slices`
- `migration plan`, `plan a migration`, `plan the migration`

## Silent On

- one-file edits and typo fixes
- split-scope meta questions such as `what does split-scope do?`
- malformed hook input, which logs to stderr and allows the prompt or tool

## Reminder

`split-scope: this prompt plans multi-slice work. Before writing the plan or PR stack, read the split-scope skill (product/skills/split-scope/SKILL.md, or the installed split-scope skill) and give each slice one review claim with a user-confirmed safety invariant.`

## Files

- `detect.py` — prompt regexes and shared reminder text
- `state.py` — Cursor-only pending reminder state under `~/.cache/catstack-split-scope`
- `claude_prompt_submit.py` — Claude inject
- `cursor_before_submit.py` / `cursor_post_tool_use.py` — Cursor parity
  (`beforeSubmitPrompt` cannot inject; reminder arrives on first `postToolUse`)
- `codex_prompt_submit.py` — Codex inject
- `install_claude_hook.py` / `install_cursor_hook.py` / `install_codex_hook.py`

## Install

`./install.sh` from the catstack repo root, then restart Claude Code, Cursor,
and Codex (Codex also needs `/hooks` trust).

## Tests

```sh
python3 -m unittest discover -s engine/hooks/split-scope/tests -v
python3 scripts/check_hook_test_coverage.py engine/hooks/split-scope
```
