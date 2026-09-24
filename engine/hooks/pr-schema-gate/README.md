# pr-schema-gate

Keeps PR text in the repo's own style without blocking anything. When a
shell tool call writes PR text directly, the hook checks that text with the
repo's own validator and tells the agent the result. The command always runs.

## Which repos are in scope

The repo is the directory holding `.git` (a directory, or a worktree's
`.git` file), found by walking up from the command's working directory. Its
validator is the first of these that exists:

1. `scripts/validate-pr-body.mjs` (Invoker)
2. `engine/skills/draft-pr/scripts/validate-pr-body.mjs` (catstack)

A repo with either is fully in scope. A PR-publishing command (`gh pr create`,
`gh pr edit` with a body, `gh api` on `pulls` with a body, `mergify stack
push`) in a git repo with neither reports UNCHECKED, naming both paths it
looked for. It is never silent. Outside any git repo the hook says nothing.
`scripts/create-pr.mjs` plays no part in scope.

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
| unchecked | inline or piped text, a missing or unreadable file, no validator at either path, `node` missing, a crash (any other exit code), a timeout (3s), an exit 0 that states no verdict and prints UNCHECKED/SKIPPED/not-installed, or a command the parser cannot read | `pr-schema-gate: could not check this PR text against the repo's PR style: <reason>. The command is not blocked.` |

An unchecked write is never reported as clean. The rules live only in the
repo's validator, so this hook carries no copy of them to drift.

A run that prints `PR body validation passed.` has judged the body, so it is
clean even when the same run names a sub-check it skipped. The catstack
validator says `Summary reading grade unchecked: ...` for a Summary too short
to grade and still accepts the body; reading that note as a vacuous pass told
the agent an accepted body was unchecked and left an owed stack follow-up
armed.

Claude Code gets the message as `additionalContext` on its `Bash` tool.
The hook's mode, harness output shape, and metrics rows are applied by the
shared hook SDK.

## Stack follow-up reminder

`mergify stack push` publishes PRs with a bare body. The push is told which
follow-up is owed (`node scripts/create-pr.mjs ... --update-existing`, or a
direct body write whose file passes the validator) and arms a pending flag.
In a repo with no validator the push reports UNCHECKED instead and arms
nothing.
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
- a `--repo` flag, or a `gh api repos/<owner>/<repo>/...` path, naming a repo
  with no local checkout under
  `PR_SCHEMA_GATE_CHECKOUTS_ROOT` (default `~/Documents/GitHub`): out of
  scope;
- a directory outside any git repo: out of scope;
- an unparseable command in a repo with no validator: silent, since it may
  not be a PR write at all.

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
- `claude_pretooluse.py` / `cursor_pretooluse.py` / `codex_pretooluse.py`:
  thin `PreToolUse` entrypoints through the shared hook SDK.
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
