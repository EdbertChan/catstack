# scope-lock

Mechanical stop for repeated task drift after the user narrows or corrects
scope. Detection is deliberately limited to agent-directed correction shapes.
Ordinary product confusion and explicit user scope expansion do not trigger
it.

Five shapes are recognised, all of them addressed at the agent rather than at
the product:

| Shape | Example |
|---|---|
| Blunt | `what are you doing`, `all I am asking`, `you are drifting` |
| Directive | `just fix it locally`, `do not use invoker` |
| Interrogative | `why are you running this locally and not in invoker?` |
| Proposal | `should we do this the same way we did in invoker?` |
| Substitution | `surprised we elected to use subagents instead of invoker` |

The last three shapes are the ones a user reaches for first, before they get
blunt, so leaving them out costs the whole early warning. Each one needs three
things in the same sentence before it counts: `you` or `we` as the actor doing
the work, a verb about performing the work, and a named alternative approach
(`instead`, `rather than`, `and not`, `the same way we did`). A question whose
subject is the product rather than the agent stays silent -- `why does the
installer merge the hook entries instead of replacing the settings file?` is
curiosity, not a correction, and a false positive here costs the user their
session.

The state machine is per harness session:

1. First same-class correction records a persistent lock. Local read-only
   tools remain available, but mutating, shell, delegated, and external tools
   are blocked until the transcript contains one standalone line:
   `SCOPE CONTRACT: <requested outcome and explicit non-goals>`.
2. The contract releases the first tool gate but stays in session state.
   Apologies and unmarked restatements never clear it.
3. A second scope correction hard-stops every tool. Another contract or
   apology cannot clear the stop. The user must explicitly invoke both
   `/reflect` and `automate-me` in the same message before tools resume.

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
