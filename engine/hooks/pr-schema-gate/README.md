# pr-schema-gate

Blocks `gh pr create` and `gh pr edit ... --body*` run directly from a shell
tool call, in any repo that has `scripts/create-pr.mjs`. Both commands
write a PR title/body straight to GitHub, skipping the make-pr/draft-pr
schema (Summary, Review Claim, Review Lane, Safety Invariant, Slice
Rationale, Non-goals, Test Plan, Revert Plan) and the `validate-pr-body.mjs`
gate that `create-pr.mjs` enforces before it writes anything.

`mergify stack push` is NOT blocked — `create-pr.mjs`'s own docs name it as
the legitimate first step of the stack flow. The required second step,
`node scripts/create-pr.mjs --title "..." --base <branch> --body-file
<file> --update-existing`, is what this hook redirects the agent to; that
tool calls `gh api repos/.../pulls` directly (not `gh pr create`/`gh pr
edit`), so it is never self-blocked.

A repo with no `scripts/create-pr.mjs` gets no block — there's no
sanctioned tool to point the agent at, so this fails open there.

**Known false positive:** matching is a raw-text regex over the whole hook
payload, not a shell parser (see `detect.py`'s docstring for why a
quote-boundary fix was tried and reverted — it also silenced the real
case). A Bash command whose text merely *contains* `gh pr create`/`gh pr
edit --body` as inert data — a heredoc, a quoted test payload, a `grep`
pattern — blocks identically to a real invocation. Found live while
smoke-testing this exact hook. If it fires on something that isn't
actually running `gh`, that's this limitation, not a new bug.

## Incident this closes

PR #10737 (`Neko-Catpital-Labs/Invoker`) sat for ~2 hours with a bare
`Depends-On: #10736` body because a Codex CLI session ran `mergify stack
push` (which auto-creates the PR) and moved on without running
`create-pr.mjs --update-existing`. Traced from the Codex session log at
`~/.codex/sessions/2026/08/27/rollout-2026-08-27T01-23-14-...jsonl`.

## Files

- `detect.py` — regex match on the raw hook payload text (not a parsed
  `tool_input` field — see its docstring for why) + repo-root walk for
  `scripts/create-pr.mjs`; target-directory resolution follows direct
  `workdir` fields and Codex's JavaScript-wrapped `workdir`
- `claude_pretooluse.py` — Claude/Cursor `PreToolUse`/`preToolUse`: exits 2
  with a stderr message when a match fires; positive-lists shell-like tool
  names only, so a `Write`/`Edit` call whose *content* mentions `gh pr
  create` never blocks
- `claude.tool.hook.json` — Claude `PreToolUse` fragment (matcher `Bash`)
- `install_claude_hook.py` / `install_cursor_hook.py` / `install_codex_hook.py`
  — merge, do not overwrite

## Codex: schema is unverified

Codex CLI (`0.146.0`) reports `hooks: stable` in `codex features list` and
tracks trusted-hash state for `hooks.json:pre_tool_use:<idx>:<idx>` in
`config.toml`, but ships no local docs for `hooks.json`'s shape. This repo
never used Codex's `pre_tool_use` hook before now (catstack's Codex
integration was `notify`-only — `turn-ended`, too late to block anything).
`install_codex_hook.py` assumes parity with Claude's
`{"pre_tool_use": [{"matcher": ..., "hooks": [{"type": "command", ...}]}]}`
shape based on the `event:idx:idx` key format, but this has **not** been
confirmed against a live Codex hook firing.

Smoke-test after installing:

```sh
cd /path/to/a/repo/with/scripts/create-pr.mjs
codex exec "run: gh pr create --title test --base main"
```

Expect Codex to report the command was blocked/denied with the
`create-pr.mjs` redirect message. If it silently runs instead, the schema
guess is wrong — check `codex debug app-server` output or
`~/.codex/log/` for what shape it actually expected, then fix
`install_codex_hook.py`'s `FRAGMENT_ENTRY`. Codex may also require
re-trusting `hooks.json`'s new content hash on next launch before it
honors the hook at all.

## Install

`./install.sh` from the repo root. Restart the harness (and see the Codex
note above — it may also need re-approval of the new `hooks.json` hash).

## Tests

```sh
python3 -m unittest discover -s hooks/pr-schema-gate/tests -v
```
