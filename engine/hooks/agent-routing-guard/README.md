# agent-routing-guard

PreToolUse hook on the **Agent** tool: refuses a subagent spawn whose prompt
carries publication work while `invoker-cli` is on PATH. Exits 2 with a
message naming the routing rule and the `invoker-plan-to-invoker` skill.

The question it asks is the *vehicle*, not the work. Nothing here judges the
task; it only refuses to let parallel subagents be the thing that commits,
pushes, merges, and opens PRs on a machine where Invoker is installed.

## Fires when both hold

1. The Agent payload's `tool_input.prompt` uses a publication verb as an
   **action**: commit, push, merge, or open / make / create / raise / file /
   submit / land a PR.
2. `invoker-cli` resolves on `PATH`.

`invoker-cli` on PATH is a **proxy** for the routing rule's own condition,
which is written in terms of Invoker's MCP tools being available. A PreToolUse
payload cannot see the harness's MCP tool list, so PATH is the observable
stand-in — the machine has Invoker installed. The two can disagree: Invoker
installed but its MCP server not connected still blocks. The block is
clearable in one line by the user, which is the right cost for that gap.

## Stays silent when

- `invoker-cli` is absent — there is nothing to route to, and a subagent is
  the only vehicle available.
- The prompt is read-only research or verification with no publication verb.
  The same words as nouns do not count: "read the last commit", "summarize
  each PR", "run the suite against the merge commit" all pass. A determiner
  in front of the word ("the", "a", "each", "last", "which", a number) is
  what marks it as a noun.
- The payload carries `agent_id` — a subagent splitting its own slice is
  executing a route somebody already chose, so re-asking there would block
  work Invoker may itself be running.
- The user's current message says "do it locally" or "don't use invoker"
  (and the near phrasings: "keep it local", "no invoker", "without invoker").

## The override check fails closed

This is the one deliberate fail-closed path, and it is worth stating plainly.
The override lives in the user's current message, which the hook reads from
the transcript. That read has **three** outcomes, not two:

| Outcome | What happens |
| --- | --- |
| The message carries an override | silent |
| The message carries no override | block, with the routing message |
| The message could not be read | block, with its own message naming the reason |

"Could not be read" means: no `transcript_path` in the payload, an unreadable
file, a file over `TRANSCRIPT_SIZE_CAP_BYTES` (32 MB), or no user line in it.
An override that cannot be read is not an override — collapsing that outcome
into "no override was given" would be wrong in the loud direction, and
collapsing it into "an override was given" would silently restore the
incident this exists to close. The block costs one turn and its message says
exactly how to clear it: route through `invoker-plan-to-invoker`, or have the
user restate the local override in this turn.

Everything else fails open: a payload that will not parse, a missing
`tool_input`, a promptless call, and any unexpected error in the detector all
let the spawn through (the last of those says so on stderr rather than
swallowing itself).

Only the **tail** of the user's message is scanned for the override. A long
message is usually a paste whose quoted text can contain "do not use Invoker"
as somebody else's dialogue; a live directive sits at the edge of what was
just typed. Same bound, and the same reason, as `scope-lock`.

## Incident this closes

One session spawned eight subagents, each of which produced a PR-worthy
commit, with `invoker-cli` on PATH and the user having asked three separate
times to route through Invoker. No hook guarded it. The only PreToolUse hook
matching the Agent tool, `engine/hooks/cat-mode-default`, injects cat-mode
into the subagent's prompt — it improves how the subagent works and never
asks whether a subagent should have been the runner.

## Files

- `detect.py` — verb detection with the noun guard, `invoker-cli` PATH
  resolution, the three-outcome override read, and `decide()`.
- `claude_pretooluse_agent.py` — Claude `PreToolUse` entrypoint; exit 2 with
  the refusal on stderr.
- `claude.agent.hook.json` — Claude `PreToolUse` fragment (matcher `Agent`).
- `install_claude_hook.py` — idempotent `settings.json` merge, never an
  overwrite.
- `tests/fixtures/*.json` — whole scenarios (invoker on PATH or not, the
  user's current message, the Agent payload) with the expected outcome.

## Install

`./install.sh` from the repo root, then restart Claude Code.

## Tests

```sh
python3 -m unittest discover -s engine/hooks/agent-routing-guard/tests -v
```
