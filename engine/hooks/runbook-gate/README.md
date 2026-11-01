# runbook-gate

One generic gate for every playbook. When `playbook-router` injects a
playbook into a session, this hook reads that playbook at the end of the turn,
records how each of its steps ended, and keeps a progress note for the
session. It speaks exactly once: a reply that claims the work is done, while a
hard step of a guided or strict playbook has no proof, is blocked.

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

A line names its step by a leading enumerator (`3.`, `- 5.`, `## 2.`), by the
words `step N` anywhere on it, or by the number straight after the colon in
the documented `override: <N> <reason>` form the block message asks for.
`skip:` or `override:` with nothing after it is not a reason, so the step stays
`unknown` — the same rule the `ship-a-detector` playbook states for its own
list. An evidence key that appears only in the agent's own prose is not
`done`: only a tool result counts.

## What blocks

Two things have to be true at once, which is why an ordinary turn never sees
this hook.

1. The reply about to be delivered claims the work is done. That reply is the
   one the stop payload names (`last_assistant_message` and the spellings the
   other two harnesses use, as `diu-stop` reads it), falling back to the
   transcript's last assistant message. Fenced blocks are stripped first, so
   pasted runner output saying `all done` is not a claim, and a negated form
   (`step 1 is not done yet`) is removed before matching.
2. Some step reaches a level this playbook's profile refuses over, and that
   step is neither `done` nor `overridden`.

A step's level is its own declared level, lowered by the playbook's
`enforcement_profile` ceiling and then checked against this hook's
`capability` list in `hooks.toml`:

| Profile | Ceiling | Refuses over |
| --- | --- | --- |
| `advisory` | `soft` | nothing |
| `guided` | `hard` | `hard` |
| `strict` | `hard` | `hard` and `conditional` |

A `skipped` step does not clear a blocking level: the playbook's own advice is
to declare the step `soft` rather than skip a check nothing ran. The policy's
`override = "reason_required"` is what makes `override: <N> <reason>` the way
out, and the reason is recorded on the step's row and in the progress note.
The block names the deficit rather than asking for different wording: every
unproven step, its evidence key, and the override line for it, so one block
and one rewrite settle the turn.

A step's `@event` names where its evidence first appears. This gate reads the
whole transcript at `Stop`, which is cumulative, so evidence produced at any
earlier event is still visible here.

## The progress note

`~/.cache/catstack-runbook/<session>.json` (or `$CATSTACK_RUNBOOK_STATE_DIR`),
written on every Stop this gate measures and read back on the next one:

```json
{"schema": "catstack.runbook_progress.v1", "playbook": "create-playbook",
 "profile": "guided", "current_step": 3,
 "steps": [{"step": 1, "rule_id": "playbook-router", "level": "hard",
            "effective_level": "hard", "status": "overridden",
            "evidence_ref": "", "reason": "the phrase came from the task",
            "proof": "the reply said override: ..."}]}
```

`current_step` is the lowest-numbered step still `unknown`, or the last step
once every one is settled. Read-back keeps the stronger of the two statuses,
so a step whose proof has aged out of the transcript — a compaction drops the
tool result that proved it — is not re-blocked on the next Stop. A note older
than a day reads as no note.

## Where rows go

`~/.cache/catstack-hook-metrics/events-<date>.jsonl` (or
`$CATSTACK_HOOK_METRICS_DIR`), as `catstack.hook_event.v1` rows through the
shared runtime — no log file of its own. One row per step, plus one row for a
block. The step rows go through the runtime's `_catstack_silent_findings`
channel: they are written with `action: silent` and never rendered, so a hook
whose mode is `stop` blocks on the one finding it returns and stays quiet
about the eight it merely recorded. A step row's `rule_id` is the step's own
rule id with its status appended (`principle-prove-it.done`), because that
schema has no free field for a status and a row that cannot name the status
cannot be counted; `subject_hash` hashes `<playbook> step <N>`, so the same
step groups across sessions whatever its status. The block row's `rule_id` is
`runbook-gate.unproven-hard-step`.

## Silent on

A session with no injected playbook (one `silent` row, no rule id). A reply
that claims nothing. A playbook whose profile refuses over nothing. A second
`Stop` in the same turn (`stop_hook_active` is set), so one block earns one
rewrite and the rewrite is never blocked again.

## Fail direction

Three outcomes, not two. Hit is the block plus one row per step, clean is one
row per step and no block, and input it could not read is one
`runbook-gate.unchecked` row and never silence:

- the stop payload names no transcript;
- the transcript cannot be opened;
- the injection names a playbook that cannot be read or decoded;
- that playbook holds no bound step lines;
- that playbook declares no `enforcement_profile`, or one that is not
  `advisory`, `guided` or `strict`, so no step's level could be resolved;
- `hooks.toml` supplies no enforcement policy for this hook.

The unchecked finding is routed through the runtime's `unchecked_fails_open`
channel, so it is written as an `unchecked` row and never blocks. A step whose
level cannot be checked on the running harness — the `capability` list names no
event of it — reaches `unchecked` on its own row with the reason, and never
counts as a step that blocks. A progress note that cannot be read fails
closed: the reason goes to stderr as a `catstack-hook-error` line, and the
session is measured from the transcript alone, which can re-block a step whose
only proof was in the lost note. Unparseable transcript lines are skipped one
by one with a `catstack-hook-error` line on stderr and the readable rows are
still measured. Garbage on stdin fails open through the SDK with a
`catstack-hook-error runbook-gate` line and no output.

## Install

Registry-driven. `hooks.toml` lists `runbook-gate` with `mode = "stop"`, so
`install.sh` symlinks the hook directory into all three harness hook
directories and `engine/hooks/_sdk/install_from_registry.py` merges
`claude.hook.json`, `cursor.hook.json` and `codex.hook.json` into the harness
configs. `scripts/install/mirror_stop_hooks_to_subagent_stop.py` adds
`SubagentStop` from the Claude manifest at the same moment, with no second
registration.
`tests/test_install.py::test_runbook_gate_is_wired_on_every_stop_event_now_that_registry_mode_is_stop`
pins both halves.

## Mode override

`CATSTACK_HOOK_MODE_RUNBOOK_GATE=warn` turns one machine's blocks into
warnings; `off` silences the hook entirely. The registry stays the default
source of the mode.

## Tests

```sh
python3 engine/hooks/runbook-gate/tests/test_runbook_gate.py
```

The blocking fixtures use the real text `engine/hooks/playbook-router/detect.py`
injects for `create playbook` against this checkout and the real bindings and
guided profile of `engine/skills/create-playbook/playbooks/create-playbook.md`,
so a router, playbook or profile change that breaks this parser fails the suite.
The advisory near neighbour keeps the real `fix the bug` router injection but
repoints its playbook source to `tests/fixtures/advisory_playbook.md`, so its
profile premise stays advisory when production playbook profiles change.
`tests/fixtures/` holds the pair: `fail_before_done_claim_over_unproven_hard_step.json`
and `pass_after_every_hard_step_proven.json` differ only in which evidence keys
reached a tool result, with `override_with_a_reason_clears_the_block.json` and
`advisory_profile_is_never_blocked.json` as the two near neighbours that must
not block.
