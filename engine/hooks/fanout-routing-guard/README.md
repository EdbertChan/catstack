# fanout-routing-guard

Claude Code `PreToolUse` hook on the `Agent` (and legacy `Task`) tool. It
blocks the second and later subagent launch in one turn when at least two of
the turn's launches may commit, push, or open PRs and nothing routed them.

This is the executable half of cat-mode's rule that publishing work is routed
by `scripts/route_execution.py` (or Invoker's `route-delegation.mjs`), never
by a fan-out default. The `cat-mode-default` hook only prepends text to each
subagent prompt; this hook can say no.

## Fires on

All of these, for the launch being made:

1. It is not the first `Agent`/`Task` launch since the latest real user
   prompt. Tool results and `<task-notification>` relays do not start a new
   turn.
2. No `Bash` call in this session ran `route_execution.py` or
   `route-delegation.mjs` and got back a result line with a known `route`.
   An errored run does not count.
3. The judge says this launch's prompt grants publishing authority, and so
   does at least one earlier launch in the turn.
4. The judge does not say the user explicitly directed subagents or said
   "do it locally".

Steps 1 and 2 read typed transcript fields. Steps 3 and 4 are meaning, so
they go to the shared [`llm-judge`](../llm-judge/README.md) through two phrase
dictionaries:

- [`fanout-routing-guard-push-authority.json`](../llm-judge/phrases/fanout-routing-guard-push-authority.json)
  reads the subagent prompt plus the head of up to two brief files the prompt
  names by absolute `.md`/`.txt` path, because a parent often puts the push
  grant in a shared brief.
- [`fanout-routing-guard-user-direction.json`](../llm-judge/phrases/fanout-routing-guard-user-direction.json)
  reads the session's user prompts. A question such as "we should be handling
  these in subagents?" is a `not_match`: a question is not a direction.

Grow either dictionary from real misses and false alarms; do not add a
pattern here.

## Stays silent on

- the first launch of a turn;
- any launch after a routing result exists in the session;
- read-only fan-outs, and a turn where only one launch publishes;
- a session where the user directed subagents or said to do it locally;
- a launch made from inside a subagent (`agent_id` set), a non-goal for now.

## Waiting on the judge

A block has to land before the launch runs, so this hook waits for the
verdict in the same call, like `diu-stop`'s plain-words check. The jobs use a
private verdict channel (`<transcript>#fanout-routing-guard`), so the hook
never drains another hook's verdicts and the shared inbox never shows these.
The wait is `FANOUT_ROUTING_GUARD_WAIT_SECONDS` (default 40). Verdicts are
cached per transcript for two hours (ten minutes for unchecked) under
`FANOUT_ROUTING_GUARD_STATE_DIR` (default `~/.cache/catstack-fanout-routing-guard`),
so each prompt is judged once.

## Block message

`fanout-routing-guard: this is subagent launch N in this turn, at least two of
them may commit, push, or open PRs, and this session has no routing result.
Run the routing table first ...` with the exact `route_execution.py` command.
When a verdict was unchecked the message adds that the judge could not decide
and why.

## Fail direction

- **Judge unchecked** (no runner answered, or no verdict inside the wait):
  fails **closed**. The launch is held, because a check that could not run is
  not a pass, and the remedy is one routing command, which also clears
  read-only fan-outs (`produces: ["report"]` routes to `subagent_fanout`).
- **Transcript missing or unreadable**: fails **open**. Without it the hook
  cannot tell whether this is a fan-out at all; it writes an `UNCHECKED`
  line to stderr and allows.
- **Verdict cache unreadable**: treated as empty and logged to stderr.
- A crash in `detect` allows, through the shared hook runtime.

## Escape hatch

Run the routing script; its result clears the hook for the session.
`CATSTACK_HOOK_MODE_FANOUT_ROUTING_GUARD=warn|off` overrides the registry's
`stop` for one machine.

## Files

- `detect.py`: transcript parsing, judge requests, the decision table.
- `claude_pretooluse_agent.py`: the entrypoint, via `_sdk/runtime.py`.
- `claude.hook.json` / `install_claude_hook.py`: the settings fragment and
  its idempotent merger.
- `tests/fixtures/incident_transcript.jsonl`: real lines from a session that
  launched 13 pushing subagents with no routing call.
