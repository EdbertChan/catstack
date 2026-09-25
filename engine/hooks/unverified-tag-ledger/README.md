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
and `has_legacy_marker` (the retired bare `UNVERIFIED:` form), both in
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
  behaviour without preventing the turn from ending at all. How much it lists
  is `CATSTACK_UNVERIFIED_TAG_BEHAVIOR` (see Env).

## Env

| Var | Effect |
|-----|--------|
| `CATSTACK_UNVERIFIED_TAG_BEHAVIOR=stale` | Default, and what an unset flag means. Re-inject only claims that have already survived `ESCALATE_AFTER_TURNS` (3) turns. |
| `CATSTACK_UNVERIFIED_TAG_BEHAVIOR=all` | Re-inject every outstanding claim on every prompt. |
| `CATSTACK_UNVERIFIED_TAG_BEHAVIOR=off` | No re-injection at all. Rows are still recorded and the Stop refusal still runs. |
| `CATSTACK_UNVERIFIED_TAG_BEHAVIOR=do_not_emit` | Refuse any reply that carries a tag outside code, well-formed or not, and inject a one-line instruction on every prompt: check the claim and paste the output, or leave it out. Not released by `stop_hook_active`, because another Stop hook's rewrite (one that asked for a tag) sets it too; deleting the sentence always ends the loop. |
| `CATSTACK_TAG_LEDGER_DIR` | Where the per-session ledger lives (the tests use a tempdir). |

`off`, `stale`, and `all` gate the injection and nothing else. `do_not_emit`
is the one setting that gates the tag itself: the unchecked claim leaves the
reply instead of being deferred in it. Every setting still records a refused
tag before refusing, so the ledger stays minable. Any value other than the four above is named on stderr and falls back
to `stale`; an `.env` candidate that exists and cannot be read is reported the
same way rather than passing as "not set".

### Drop counter

Each `do_not_emit` refusal adds to the row's `refusals`. When a refused claim
leaves the reply, the row closes with `outcome: dropped` (no verification tool
ran that turn) or `outcome: checked` (one did). A turn whose tool list could
not be read closes nothing. Totals across every session:

```sh
python3 engine/hooks/unverified-tag-ledger/detect.py stats
```

prints `refused_claims`, `dropped`, `checked`, `still_open`, and
`unreadable_rows`. A rising `dropped` share means the setting is making replies
say less rather than making claims get checked, which is the known cost of a
drop policy: instruction tuning on abstention-aware data "can lead to
over-abstention" (Wen et al., "Know Your Limits: A Survey of Abstention in
Large Language Models", 2024, https://arxiv.org/abs/2407.18418).

The hook resolves this flag itself through `engine/hooks/_flags/flags.py`.
The `enabled_by` line in `engine/hooks/hooks.toml` records which flag the hook
answers to; nothing reads that field, so it is documentation, not the gate.
- **Discharge** — a claim is resolved when a later turn runs a verification tool
  (`Bash`, `Read`, `Grep`, `Glob`, `NotebookRead`) and stops re-emitting it.
- **Where the turn's tool list comes from** — the transcript named by
  `transcript_path`, read the way `scope-lock/detect.py` reads it. A Claude Code
  Stop payload carries no tool list of any kind; the captured one in
  `tests/fixtures/claude-stop-payload.json` is the record of that. The read has
  three outcomes, not two: a set of names, an empty set, and *unchecked* when
  the transcript is missing or unreadable. Unchecked is not "no tools" — an
  unchecked turn is neither refused nor allowed to discharge a row, and the
  reason is written to stderr.
- **Escalation** — a claim outstanding `ESCALATE_AFTER_TURNS` (3) turns or more
  is reported as a reflect trigger rather than accumulating quietly.
- **Discharge is itself a reflect trigger** — a row going outstanding ->
  discharged is the record of a claim that went out first and was checked
  after. That is an evidence-order miss, and it carries no wrongness word, so
  the phrase scanners (`engine/skills/reflect/scripts/self_retraction_scan.py`,
  and the `wrong-check-reflect` dictionary) cannot see it from the text. This
  hook sees it from state instead, and says so on the Stop that discharges.

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
corrupt-row report. `tests/test_backtest_judge.py` adds 8 more for the backtest
script below, using a stub model.

## Backtest: should a background judge check each tag's blocker?

Not yet. The ledger has no model judge, and the one idea tried so far scored
worse than a rule that needs no model.

`backtest_judge.py` replays labeled tags through the real llm-judge in
investigate mode (read-only Read, Grep and Glob). For each case it copies the
transcript up to the reply that carries the tag, so the judge cannot see what
happened later, and starts the judge in that session's working folder. It asks
whether the named blocker was false and scores the answer against a label.
A case the judge cannot answer is counted as unchecked, never as a pass.

```
python3 engine/hooks/unverified-tag-ledger/backtest_judge.py \
  --cases CASES.jsonl --labels LABELS.jsonl --out RESULTS.jsonl
```

Cases and labels stay outside the repo because they point at private
transcripts. `CASES.jsonl` rows are `{"id", "session", "tag"}`; `LABELS.jsonl`
rows are `{"id", "blocker": "true"|"false"|"unclear"}`.

Result on 44 real well-formed tags from 21 sessions, labeled by a stronger
model that could read the whole transcript and any file on the machine
(33 blockers false, 10 real, 1 unclear):

| | blocker really false | blocker really real |
|---|---|---|
| judge said false | 22 | 5 |
| judge said real | 11 | 5 |

The judge was right on 27 of 43 labeled cases (63%). Answering "false" every
time is right on 33 of 43 (77%). Every answer came from the codex runner, so
the claude runner was never exercised.

Two failure shapes showed up in the judge's own reports:

- It searched only the transcript copy. Blockers that were false because the
  answer sat in another file on disk (a codex session log, a restart log under
  `~/.invoker/`) were called real.
- In 2 of the 5 wrong "false" calls, its report said the claim could not be
  established while its `blocker_false` field said true.

A judge is worth wiring into the ledger only after a rerun of this backtest
beats the always-false rule. The labels come from a model, not a person, so a
run that clears that bar should also be spot-checked by hand.

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
