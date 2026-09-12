# unverified-tag-ledger

A well-formed `{{CAT-UNVERIFIED: <claim> -- cannot verify: <reason>}}` tag is a
**deferral**, not a discharge. This hook makes that true mechanically.

## The gap it closes

`cat-mode/SKILL.md:269` says:

> Any hedge auto-runs prove-it in the same turn — a hedge is a trigger to
> verify, never a place to stop.

Every evidence hook implemented the opposite. `_markers/markers.py` defines
`excuses_paragraph()`, and consumers treat a well-formed tag as equivalent to
evidence — for example `prove-it-ship-gate/detect.py`:

```python
if markers.well_formed_tags(message) or has_evidence(message):
```

Only the *broken* tag shapes ever fired: `malformed_tags` (names no blocker)
and `has_legacy_marker` (bare `UNVERIFIED:`), both in
`diu-stop/claude_stop_check.py`. A correctly-formed tag produced silence from
the entire stack, was counted nowhere, and was revisited never. The written
rule said "never a place to stop" while the tooling rewarded stopping.

Observed 2026-09-11 (NiceSpeak streaming session): two well-formed tags were
emitted, each ended its turn, and neither left a trace. Both are the positive
fixtures in `tests/test_hooks.py`.

## What it does

- **Stop** (`claude_stop_check.py`) — parses well-formed tags out of the reply
  and appends them to a per-session ledger, then **refuses the turn** (exit 2)
  if it tagged a claim without running any verification tool. A tag earns its
  place only after an attempt: requiring an attempt is not requiring success, so
  run the check and tag it only when the check cannot settle the claim.
  `stop_hook_active` releases the refusal, or the rewrite turn — which has no
  tool call of its own — would loop forever.
- **UserPromptSubmit** (`claude_prompt_reminder.py`) — lists outstanding claims
  on the next prompt, quoting the rule and naming each claim plus what it is
  blocked on. The next prompt is the earliest point a reminder can change
  behaviour without preventing the turn from ending at all.
- **Discharge** — a claim is resolved when a later turn runs a verification tool
  (`Bash`, `Read`, `Grep`, `Glob`, `NotebookRead`) and stops re-emitting it.
- **Escalation** — a claim outstanding `ESCALATE_AFTER_TURNS` (3) turns or more
  is reported as a reflect trigger rather than accumulating quietly.

Malformed tags are deliberately ignored here; `diu-stop` already rejects those.

## Ledger

`~/.cache/catstack-unverified-ledger/<session_id>.jsonl`, one JSON row per
claim (`claim`, `reason`, `first_seen`, `turns`, `resolved`). Override the
directory with `CATSTACK_TAG_LEDGER_DIR` (the tests use a tempdir). A row that
is not JSON is reported on stderr and skipped, never silently dropped.

## Tests

```
cd engine/hooks/unverified-tag-ledger && python3 -m unittest discover -s tests
```

17 tests: both real tags as positive fixtures, the refusal on an untried tag, the `stop_hook_active` release that prevents a refusal loop, a no-tag negative control, the
malformed-tag negative, discharge-on-verify, stays-outstanding-without-verify,
no duplicate on re-emit, stale escalation, per-session isolation, and the
corrupt-row report.

## Prior art

The shape is a **defect-tracking rule**: a known-unresolved item is recorded
and re-surfaced rather than left to memory. Nancy G. Leveson, *CAST Handbook:
How to Learn More from Incidents and Accidents*, 2019
(https://psas.scripts.mit.edu/home/get_file4.php?name=CAST_Handbook.pdf) names
the failure this prevents — "fixing the symptoms of problems but not tackling
the systemic causes" — by requiring the count be published before any single
item is called fixed. Saltzer and Schroeder, "Basic Principles of Information
Protection", 1975
(https://web.mit.edu/Saltzer/www/publications/protection/Basic.html) supplies
the default: base the decision on explicit permission, so absence of a check is
never read as a pass.
