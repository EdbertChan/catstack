# runbook-gate

One generic gate for every playbook. When `playbook-router` injects a
playbook into a session, this hook reads that playbook at the end of the turn
and records how each of its steps ended. It never speaks: its registry mode is
`off`, so measurement lands before any step turns hard.

## Fires on

| Harness | Event | Entrypoint |
| --- | --- | --- |
| Claude | `Stop`, and `SubagentStop` through the manifest mirror | `claude_stop_check.py` |
| Cursor | `stop` | `cursor_stop_check.py` |
| Codex | `Stop` | `codex_stop_check.py` |

The session's playbook comes from the router's own injected text, found in the
transcript the stop payload names (`agent_transcript_path`, `transcript_path`,
`transcriptPath`, or the Codex rollout for a `thread-id`). The injection is
recognised by its two first lines — `Playbook: <name>` followed by `Read and
apply the full source at <paths>, including its constraints.` — which is how
Claude stores a `UserPromptSubmit` `additionalContext` row
(`attachment.type: hook_additional_context`) and how the other two harnesses
carry it. The last injection in the session wins. The paths on that line are
the playbook itself, and the steps are read from the file, not from the
shortened heading list the router injects.

A step is one line: `## N. Title [rule-id · level · evidence: key · @event]`.

## What each status means

| Status | How it is decided | Where the proof is |
| --- | --- | --- |
| `done` | the step's evidence key appears as a whole word in a tool result this session | the transcript path and the key |
| `skipped` | the reply wrote `skip: <reason>` on a line that names the step number | the reason the reply gave |
| `overridden` | the reply wrote `override: <reason>` on a line that names the step number | the reason the reply gave |
| `unknown` | none of the above, or the binding names no evidence key at all | what was looked for and not found |

A line names its step either by a leading enumerator (`3.`, `- 5.`, `## 2.`)
or by the words `step N` anywhere on it. `skip:` or `override:` with nothing
after it is not a reason, so the step stays `unknown` — the same rule the
`ship-a-detector` playbook states for its own list. An evidence key that
appears only in the agent's own prose is not `done`: only a tool result counts.

## Where rows go

`~/.cache/catstack-hook-metrics/events-<date>.jsonl` (or
`$CATSTACK_HOOK_METRICS_DIR`), as `catstack.hook_event.v1` rows through the
shared runtime — no log file of its own. One row per step. The row's `rule_id`
is the step's own rule id with its status appended (`principle-prove-it.done`),
because that schema has no free field for a status and a row that cannot name
the status cannot be counted; `subject_hash` hashes `<playbook> step <N>`, so
the same step groups across sessions whatever its status.

## Silent on

A session with no injected playbook (one `silent` row, no rule id). A second
`Stop` in the same turn (`stop_hook_active` is set), so a blocked-and-rewritten
turn is not counted twice. Any mode other than `off` would render a message;
nothing in this slice blocks, warns, or writes a progress note.

## Fail direction

Three outcomes, not two. Hit is one row per step, clean is one silent row, and
input it could not read is one `runbook-gate.unchecked` row and never silence:

- the stop payload names no transcript;
- the transcript cannot be opened;
- the injection names a playbook that cannot be read or decoded;
- that playbook holds no bound step lines.

The unchecked finding is routed through the runtime's `unchecked_fails_open`
channel, so it is written as an `unchecked` row and never blocks. Unparseable
transcript lines are skipped one by one with a `catstack-hook-error` line on
stderr and the readable rows are still measured. Garbage on stdin fails open
through the SDK with a `catstack-hook-error runbook-gate` line and no output.

## Install

Registry-driven. `hooks.toml` lists `runbook-gate` with `mode = "off"`, so
`install.sh` symlinks the hook directory into all three harness hook
directories, and `engine/hooks/_sdk/install_from_registry.py` merges
`claude.hook.json`, `cursor.hook.json` and `codex.hook.json` into the harness
configs once the mode leaves `off` — an `off` hook ships linked and unwired, as
`skill-usage-log` and `unverified-tag-check` do.
`scripts/install/mirror_stop_hooks_to_subagent_stop.py` adds `SubagentStop`
from the Claude manifest at the same moment, with no second registration.
`tests/test_install.py::test_runbook_gate_is_linked_but_not_wired_while_registry_mode_is_off`
pins both halves.

## Mode override

`CATSTACK_HOOK_MODE_RUNBOOK_GATE=warn` makes one machine's step rows visible as
warnings. The registry stays the default source of the mode.

## Tests

```sh
python3 engine/hooks/runbook-gate/tests/test_runbook_gate.py
```

The positive fixtures are the real text `engine/hooks/playbook-router/detect.py`
injects for `create playbook` against this checkout, and the real bindings of
`engine/skills/create-playbook/playbooks/create-playbook.md`, so a router or
playbook change that breaks this parser fails the suite.
