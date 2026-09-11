# pr-schema-gate

Keeps PR text in the repo's own style without blocking anything. In any repo
that has `scripts/create-pr.mjs`, when a shell tool call writes PR text
directly, the hook checks that text with the repo's own
`scripts/validate-pr-body.mjs` and tells the agent the result. The command
always runs.

## What counts as a direct PR text write

The hook parses the shell command into the commands it will run
(`shell_model.py`, the standard library's POSIX shell lexer) and decides on
their words, not on the raw text:

- `gh pr create`
- `gh pr edit` with `--body`, `-b`, `--body-file`, or `-F`
- `gh api` on a `pulls` endpoint with a `body=` field (`-f`, `-F`,
  `--field`, `--raw-field`)

Silent, by construction: `gh pr edit` with only `--title`; `gh api` reads,
title-only patches, and `issues` endpoints; `create-pr.mjs`'s own
`gh api ... pulls --input -` shape; any other program whose arguments merely
mention one of these commands (a `grep` pattern, an `echo`, a quoted test
payload); heredoc bodies; `Write`/`Edit` tool calls.

## What the agent is told

Three outcomes, never two:

| Outcome | When | Message |
|---|---|---|
| clean | the validator exits 0 | nothing |
| failed | the validator exits 1 | `pr-schema-gate: the PR text in <file> does not follow this repo's PR style ... The command is not blocked.` plus the validator's error lines (up to 20) |
| unchecked | inline or piped text, a missing or unreadable file, no validator, `node` missing, a crash (any other exit code), a timeout (3s), or a command the parser cannot read | `pr-schema-gate: could not check this PR text against the repo's PR style: <reason>. The command is not blocked.` |

An unchecked write is never reported as clean. The rules live only in the
repo's validator, so this hook carries no copy of them to drift.

Claude Code gets the message as `additionalContext` on its `Bash` tool.
Every harness also gets it on stderr. Whether Cursor and Codex show a
stderr line from an exit-0 `preToolUse` hook to the agent is unverified.

## Stack follow-up reminder

`mergify stack push` publishes PRs with a bare body. The push is told which
follow-up is owed (`node scripts/create-pr.mjs ... --update-existing`, or a
direct body write whose file passes the validator) and arms a pending flag.
A later push while the flag is armed repeats the reminder. Either follow-up
clears it; an unchecked or failing direct write does not.

- `--dry-run` publishes nothing: it neither arms nor reminds.
- `PreToolUse` fires before the command, so pending is recorded when the
  push is let through. A push that then fails leaves one stale reminder,
  cleared by the next follow-up or the TTL.
- State is one small JSON file per repo root, in the temp dir, never in the
  worktree. Override the location with `PR_SCHEMA_GATE_STATE_DIR`.
- It expires after `PENDING_TTL_SECONDS` (2h).

## Fail direction

The hook never blocks, so every failure fails open, and says so:

- unreadable hook payload, or an internal error: one stderr line naming it,
  nothing checked;
- missing, unreadable, malformed, future-dated, or expired state: nothing
  owed;
- a `--repo` naming a repo with no local checkout under
  `PR_SCHEMA_GATE_CHECKOUTS_ROOT` (default `~/Documents/GitHub`): out of
  scope;
- a repo with no `scripts/create-pr.mjs`: out of scope.

There is no escape hatch because there is nothing to escape.

## Incident this closes

PR #10737 (`Neko-Catpital-Labs/Invoker`) sat for ~2 hours with a bare
`Depends-On: #10736` body because a Codex CLI session ran `mergify stack
push` and moved on without running `create-pr.mjs --update-existing`.

## Files

- `shell_model.py`: boundary parser from a tool call (Claude/Cursor
  `command`, Codex `cmd`, argv lists, and Codex's JavaScript-wrapped
  `exec_command({...})`) to `Command(argv, cwd)` values, following `cd`
  and explicit `workdir`. A quoted argument that spans lines (a multi-line
  `git commit -m "..."`) stays one word; only a quote that never closes
  makes the command unparseable.
- `detect.py`: classification of commands, target-repo resolution, the
  validator call, and the pending state.
- `claude_pretooluse.py`: the `PreToolUse` entrypoint for all three
  harnesses; exit 0 always.
- `claude.tool.hook.json`: Claude `PreToolUse` fragment (matcher `Bash`).
- `install_claude_hook.py` / `install_cursor_hook.py` / `install_codex_hook.py`:
  merge, do not overwrite.

## Codex: schema is unverified

`install_codex_hook.py` assumes Codex's `hooks.json` matches Claude's
`{"pre_tool_use": [{"matcher": ..., "hooks": [{"type": "command", ...}]}]}`
shape. This has not been confirmed against a live Codex hook firing. Codex
may also require re-trusting `hooks.json`'s new content hash before it runs
the hook.

## Install

`./install.sh` from the repo root, then restart the harness.

## Tests

```sh
python3 -m unittest discover -s engine/hooks/pr-schema-gate/tests -v
```
