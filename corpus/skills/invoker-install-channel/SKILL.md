---
name: invoker-install-channel
description: >
  Apply when installing, updating, starting, configuring harness MCP,
  querying, submitting, or reporting Invoker (npm packages vs a git
  checkout, or a path under /opt/homebrew). Stay on npm; never use
  ./run.sh for Invoker ops.
---

# Invoker install channel

## Invariants (assert)

- Invoker is distributed via npm (`@neko-catpital-labs/invoker-ui`,
  `invoker-cli`, `invoker-slack`), not Homebrew. `/opt/homebrew/...` is
  only a filesystem prefix for global npm — never call that install
  "Homebrew."
- Never use `./run.sh` to talk to Invoker (query/submit/ops). Use npm
  `invoker-cli mcp` / `invoker-ui --headless` against the live owner
  only.
- Cursor / Claude / Codex Invoker MCP must launch npm `invoker-cli mcp`
  (e.g. `/opt/homebrew/bin/invoker-cli mcp`), never a git-checkout
  `packages/cli/dist/index.js mcp`.
- If npm cannot serve, say so and stop. Do not start a checkout
  Electron.
- When reporting install or update status, name the command actually
  run. Do not infer a distribution channel from a path prefix.

**Why:** npm's global prefix can be `/opt/homebrew/` without Homebrew
being the distribution channel.

## Incident

Adapted from unmerged `reflect/invoker-npm-channel-20260825` (closed
PR #41). Cursor MCP launched checkout `packages/cli/dist/index.js mcp`
while the live owner was npm `invoker-ui` 0.0.14. Agents issued
`./run.sh` instead of talking to that owner. User 2026-08-27: do not
run `./run.sh`; use the current running invoker-ui.
