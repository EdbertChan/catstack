# scope-lock

Mechanical stop for repeated task drift after the user narrows or corrects
scope. Detection is deliberately limited to agent-directed correction shapes
(`what are you doing`, `why did you expand`, `all I am asking`, `do it
locally`, `you are drifting`). Ordinary product confusion and explicit user
scope expansion do not trigger it.

The state machine is per harness session:

1. First same-class correction records a persistent lock. Local read-only
   tools remain available, but mutating, shell, delegated, and external tools
   are blocked until the transcript contains one standalone line:
   `SCOPE CONTRACT: <requested outcome and explicit non-goals>`.
2. The contract releases the first tool gate but stays in session state.
   Apologies and unmarked restatements never clear it.
3. A second scope correction hard-stops every tool. Another contract or
   apology cannot clear the stop. The user must explicitly invoke both
   `/reflect` and `automate-me` before tools resume.

State lives under `~/.cache/catstack-scope-lock/` and is keyed by session or
conversation ID (falling back to transcript path). Hook failures are fail-open
so a corrupt cache cannot brick the harness.

## Harness support

| Harness | Detection | Enforcement |
|---|---|---|
| Claude Code | `UserPromptSubmit` | `PreToolUse` blocks tools with exit 2. |
| Cursor | `beforeSubmitPrompt` | `preToolUse` returns `continue: false`. |
| Codex CLI/app | `UserPromptSubmit` | Native `PreToolUse` returns `permissionDecision: "deny"`. Hosted tools are outside the local hook path, so this remains a guardrail rather than a complete enforcement boundary. |

The Claude, Cursor, and Codex wrappers share `detect.py`, state format, correction
fixtures, and state-machine tests. This prevents their behavior from drifting
even though their hook response schemas differ.

## Install

Run `./install.sh`, then restart Claude Code, Cursor, and Codex. The installer
links the hook directory into each harness and idempotently merges the hook
entries without replacing unrelated settings. Codex requires reviewing and
trusting new or changed definitions through `/hooks` before they run.

## Tests

```sh
python3 -m unittest discover -s engine/hooks/scope-lock/tests -v
python3 scripts/check_hook_test_coverage.py engine/hooks/scope-lock
```
