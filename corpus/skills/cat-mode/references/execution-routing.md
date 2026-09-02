# Execution routing

Catstack owns judgment and local fallback. Invoker owns durable plan submission, execution, status, and recovery when its MCP tools are available.

## Decision

1. **Invoker unavailable** (no `invoker_prepare_plan_review` / `invoker_submit_plan` tools): stay local — subagents, `loop-generator`, `land-stack`, current chat execution.
2. **Small local work** (one-file fix, short edit, read-only question): stay local even if Invoker is installed. Post-land wait until `MERGED`, merge-queue babysit, and already-named execution Backlog are **not** this bucket — they are `durable_parallel`.
3. **Approved plan or durable/parallel work** and Invoker MCP is available: delegate. If Invoker is missing, use a separate git worktree + PR stack. Do not park that work in the parent chat.

Durable/parallel means multi-step work that benefits from a persisted task graph, isolated worktrees, retries, or unattended watching — not every commit-and-push. Aliases `post_land_babysit` and `named_execution_backlog` classify as `durable_parallel`.

## Delegated lifecycle

Do not invent Invoker YAML schema, CLI flags, database reads, or recovery paths here.

1. Follow the installed Invoker `chat-submit` / `plan-to-invoker` skills to produce a plan.
2. `invoker_prepare_plan_review` with exactly one of `planPath` or `sessionId`.
3. Show ordered steps in chat, not only inside the approval question; keep `reviewToken`.
4. One explicit user approval (unless review says `auto_submit`); never two "(Recommended)" options. For a fan-out, submit one head and see it run before the rest.
5. `invoker_submit_plan` with the same source + `reviewToken`.
6. Bounded waits / status reads: `invoker_wait_for_workflow`, `invoker_get_workflow`, `invoker_list_tasks`.
7. Report completion, blocker, or approval gate. Use Invoker `invoker-ops` for retries/cancels.

## Hard boundaries

- Catstack does not embed Invoker command maps or database access.
- Prefer extending an existing durable mechanism (Invoker worker when available, otherwise an existing skill/loop) over a new one-off cron.
- Automated `reflect-ci-*` mining belongs to Invoker's `reflect-ci` skill, not catstack `reflect`.
- Local unattended work uses `show-me-your-work`. Invoker-delegated work uses Invoker workflow status, not a second TSV.
