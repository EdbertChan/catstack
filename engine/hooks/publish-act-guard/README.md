# publish-act-guard

Refuses a publishing command from a second subagent in the same session,
within 30 minutes of another subagent's publish, while a live Invoker owner is
reachable. Parallel publishing work routes through Invoker; a single subagent
that finishes its work and pushes is not blocked.

## Why only the second publisher

The incident behind this gate (2026-09-09) was eight subagents each publishing
from one session. The first version blocked every subagent publish while
Invoker answered. Over 2026-09-14..25 it blocked 25 times across 7 sessions,
and each block moved a single subagent's final push back to the parent
session, which is never gated, often through a hand-off to the user. The
parallel case is the one worth stopping, so the gate now records the first
publisher per session and refuses a different one inside the window.

## Fires on

A shell-like PreToolUse call whose command, parsed at command position, performs
one of: `git push`, `gh pr create|merge|ready`, a mutating `gh api` call against
`/pulls`, `mergify stack push`, `create-pr.mjs`, `safe-stack-push.mjs --execute`.
All four must hold: the caller is a subagent, the act is one of those, a
different subagent in the same session published within the last 30 minutes,
and the liveness probe reports a reachable owner.

## Silent on

- The main session — routing is the parent's decision, taken once.
- Every read-only neighbour: `gh pr view`, `gh pr checks`, `gh api ... --jq`,
  `git log`, a filename argument such as `cat scripts/safe-stack-push.mjs`, and
  a mention of a command inside a quoted string or grep pattern.
- Any dry run: `git push --dry-run`, `safe-stack-push.mjs` without `--execute`.
- No reachable owner — if Invoker cannot take the work, the subagent publishes.

## Replaces agent-routing-guard

The predecessor classified the spawn prompt with regexes over prose. "carrying
commits" parsed as an action because its noun test required a determiner, and
deleting the word cleared the block without changing what the subagent would do.
Its override check read only text blocks, so an answer given through
`AskUserQuestion` never counted as approval. This hook reads the command, which
is a typed field, and never the prompt.

## Fail direction

- Payload will not parse, non-shell tool, no command string: open, reason on stderr.
- Caller is not a subagent, command is not a publishing act: open, reason recorded
  (set `PUBLISH_ACT_GUARD_DEBUG=1` to see it).
- Liveness unreadable (probe timed out or errored): open, and the block message
  says UNCHECKED so the report has to name it.
- No session id in the payload, or the publisher ledger unreadable: open, UNCHECKED.
- Owner reachable and a second subagent in the session publishing inside the
  window: closed.

## Publisher ledger

`$TMPDIR/publish-act-guard-publishers.json` maps session id to subagent id to
the time of its first allowed publish. Entries older than the window are
dropped on each write.

## Block message and escape hatch

The refusal names the act and the other subagent, and points at the
`invoker-plan-to-invoker` skill. It also says the subagent can finish without
publishing and hand the commit to the parent session, which is never gated. It
clears on its own when no live owner answers or when the window passes.

## Liveness probe

`invoker-cli query capacity --output json`, 8s timeout, cached 120s in
`$TMPDIR/publish-act-guard-liveness.json`. An injected probe (tests) bypasses the
cache entirely.
