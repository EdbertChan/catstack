# Transcript locations

Read this when running reflect step 1 (single-transcript mode).

## Claude Code (default)

Claude Code stores session transcripts as JSONL under `~/.claude/projects/<encoded-cwd>/*.jsonl`, where `<encoded-cwd>` is the absolute working directory with every `/` replaced by `-` (e.g. `/Users/x/repo` → `-Users-x-repo`). Take the most recently modified file in that directory unless the user names a different project or session. Each line is JSON with a `type` field (`"user"` / `"assistant"` carry the conversation; skip other types like `mode` or `file-history-snapshot`); message text is at `.message.content`, either a plain string or a list of blocks (`text`, `thinking`, `tool_use`, `tool_result`).

A transcript's last turn is not guaranteed to reflect the task's actual final outcome — an Invoker-orchestrated task's finalize/commit step can happen outside the agent's own captured session (e.g. a session that ends mid-`Monitor`-wait on a backgrounded test, with the resulting commit and passing verification appearing only in `git log`, never in that JSONL). Corroborate completion against `git log`/the task's recorded summary before treating a transcript's tail as proof the work finished, succeeded, or failed.

## Other tools

- Codex sessions live at `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`, with per-turn usage under `event_msg` → `payload.type == "token_count"`, and a `rate_limits.primary.used_percent` field on the same event that tracks the account's rolling quota — useful for telling "this session burned quota fast" apart from "the account was already near its cap before this session started."
- OMP sessions live at `~/.omp/agent/sessions/**/*.jsonl` (exclude `merge-clones` / `--private-tmp--` worker dirs — those are automated, not interactive work). Each assistant `message` event carries `usage.input/output/cacheRead/cacheWrite` plus an already-computed `usage.cost.total` in dollars — the richest of the four, no pricing table needed.
- Cursor sessions live at `~/.cursor/projects/<project>/agent-transcripts/<uuid>/<uuid>.jsonl`. Verified against real transcripts: these carry no token/usage/model fields at all, so `cursor` mode can only report thrash (redundant tool calls), never token or cost numbers. Say that limitation out loud in the summary rather than silently omitting Cursor's cost line.
