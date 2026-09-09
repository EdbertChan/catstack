# agent-relay-attribution

Advisory Stop hook: a fact relayed from a subagent is the agent's claim,
not the reply's own observation. When a subagent result arrived within the
last three turns and the outgoing reply states facts (passed, merged,
fixed, landed, green, because, numbers) without saying where they came from
("per the agent's report", "the agent reported", "relayed") and without
this turn's own command output showing any of those facts, the hook emits
"attribute relayed claims or re-verify (agent-relay-attribution)". It never
blocks: exit 0, the note goes to stderr and to the harness as a
`systemMessage`.

## What counts as a relay arriving

Both shapes a subagent's words take in the parent's transcript:

- a `<task-notification>` block, and
- a teammate message, the envelope a message between agents lands in:
  `<teammate-message teammate_id="architect" color="green" summary="...">`
  ... `</teammate-message>`, one user line often carrying several.

Envelopes that are only harness control payloads do not count: a
`teammate_id="system"` envelope, or a body that is a JSON object with a
`type` (`teammate_terminated`, `shutdown_approved`). Nobody claimed
anything in those.

## What counts as verifying it

A verification tool having run in the turn is not enough -- a `Read` of an
unrelated file would otherwise silence every reply. The tool result itself
has to contain one of the facts the reply asserts: a status word (passed,
merged, landed, green, ...) or a number of two or more digits, matched
against the output of a `Bash`/`Read`/`Grep`/`Glob`/`Monitor`/`WebFetch`
call in the same turn, keyed by `tool_use_id` so a result only counts for
the tool that produced it. Single digits and a bare "because" are dropped
as corroboration -- too common in unrelated output to prove anything. A
command that printed nothing corroborates nothing.

One overlapping fact is enough to stay silent. Whether *every* number in
the reply is covered stays with the model; this file matches shapes.

The shape it targets: "First PR is open: ... (six coverage gates, 187 tests
passing)" sent right after the agent's notification, where nothing in the
turn ran those tests. The same reply with "Per the agent's report: 24 new
tests, suite `271 passed`" passes, as does a reply in a turn that re-ran the
suite and shows the line.

Fail-open on parse or read errors; no transcript means no arrival to check.

## Files

- `detect.py` -- fact, attribution, arrival, and evidence logic; `decide()`.
- `claude_stop_check.py` -- Claude Stop entrypoint (advisory).
- `claude.hook.json` / `install_claude_hook.py` -- settings.json merge (idempotent).
- `tests/fixtures/relay_{fires,silent}.json` -- sanitized real replies with
  their transcripts, both arrival shapes.
- `tests/test_hooks.py`

Tests: `python3 -m unittest discover -s engine/hooks/agent-relay-attribution/tests -v`
