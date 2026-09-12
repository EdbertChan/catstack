# publish-act-guard

Refuses a publishing command issued from inside a subagent while a live Invoker
owner is reachable, so publishing work routes through Invoker instead of
fanning out across parallel subagents.

## Fires on

A shell-like PreToolUse call whose command, parsed at command position, performs
one of: `git push`, `gh pr create|merge|ready`, a mutating `gh api` call against
`/pulls`, `mergify stack push`, `create-pr.mjs`, `safe-stack-push.mjs --execute`.
All three must hold: the caller is a subagent, the act is one of those, and the
liveness probe reports a reachable owner.

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
- Owner reachable and a subagent is publishing: closed.

## Block message and escape hatch

The refusal names the act and points at the `invoker-plan-to-invoker` skill. It
clears on its own when no live owner answers. The user clears it deliberately by
saying "do it locally" or "don't use invoker", which routes the work here rather
than to Invoker.

## Liveness probe

`invoker-cli query capacity --output json`, 8s timeout, cached 120s in
`$TMPDIR/publish-act-guard-liveness.json`. An injected probe (tests) bypasses the
cache entirely.
