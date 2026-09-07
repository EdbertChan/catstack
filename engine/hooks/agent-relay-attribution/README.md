# agent-relay-attribution

Advisory Stop hook: a fact relayed from a subagent is the agent's claim,
not the reply's own observation. When a task-notification (a subagent
result) arrived within the last three turns and the outgoing reply states
facts (passed, merged, fixed, landed, green, because, numbers) without
saying where they came from ("per the agent's report", "the agent
reported", "relayed") and without a verification command this turn (Bash,
Read, Grep, Glob), the hook emits "attribute relayed claims or re-verify
(agent-relay-attribution)". It never blocks: exit 0, the note goes to
stderr and to the harness as a `systemMessage`.

The shape it targets: "First PR is open: ... (six coverage gates, 187 tests
passing)" sent right after the agent's notification, where nothing in the
turn ran those tests. The same reply with "Per the agent's report: 24 new
tests, suite `271 passed`" passes, as does a reply in a turn that re-ran the
suite.

Whether a specific number is really a relay stays with the model. Fail-open
on parse or read errors; no transcript means no notification to check.

## Files

- `detect.py` -- fact, attribution, and turn-boundary logic; `decide()`.
- `claude_stop_check.py` -- Claude Stop entrypoint (advisory).
- `claude.hook.json` / `install_claude_hook.py` -- settings.json merge (idempotent).
- `tests/fixtures/relay_{fires,silent}.json` -- sanitized real replies with
  their one-turn transcripts.
- `tests/test_hooks.py`

Tests: `python3 -m unittest discover -s engine/hooks/agent-relay-attribution/tests -v`
