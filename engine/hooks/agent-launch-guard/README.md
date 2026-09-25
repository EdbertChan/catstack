# agent-launch-guard

Claude-specific `PreToolUse` warning hook for `Agent` and `Task` launches.
The harness scope is intentionally Claude-only because `Agent`/`Task` are
Claude tool events; this hook does not claim equivalent visibility in Cursor
or Codex.

When `CATSTACK_AGENT_LAUNCH_BUDGET` is unset or `off`, the hook is silent.
Otherwise it accepts `MAX[:WINDOW_SECS]`, with a 600-second default window.
Malformed values are silent. Each launch appends to
`~/.catstack/agent-launch-ledger.jsonl`, or to `CATSTACK_AGENT_LAUNCH_LEDGER`,
and old rows are pruned from the sliding window.

The hook emits one advisory warning when a session crosses `MAX` launches in
the window. It never blocks, rewrites, or delays a launch. Ledger and
environment failures fail open and write a non-silent error to stderr.

Install wiring is in the repository root `install.sh`; the hook manifest is
merged into Claude's `~/.claude/settings.json` under `PreToolUse` with mode
`warn` in `engine/hooks/hooks.toml`.
