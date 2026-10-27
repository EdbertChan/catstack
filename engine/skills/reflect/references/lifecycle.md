# Lifecycle pass (revisit old rules)

Read this for the opt-in weekly pass that reads the last 60 days of the
stack's own records and proposes, for a person to decide, which skill, hook,
or playbook step should change. It is the other half of reflect: reflect adds
rules, the lifecycle pass revisits the ones already shipped.

```bash
python3 engine/skills/reflect/scripts/lifecycle.py report
python3 engine/skills/reflect/scripts/lifecycle.py report --open-prs
./install.sh --with-lifecycle   # Mon 11:00 launchd, report --open-prs
```

## Signals it reads

One pass over the window's own records — no model is asked except for the
overlap question below:

- **Mined clusters** — the mine queue at `~/.cache/catstack-session-mine/queue.json`
  (`--state-dir`). Every cluster is given an owner skill from the fixed
  cluster-owner table; a cluster the table does not name is a coverage gap.
- **Skill-use rows** — the `skill_used` events every harness wrote, under
  `~/.cache/catstack-hook-metrics` (`--metrics-dir`), counted per skill across
  Claude, Cursor, and Codex.
- **Hook rows per rule** — each rule's fires, stops, warns, ignores,
  overrides, and unchecked counts, with its effective level and the hook
  runner's own per-rule suggestion.
- **Step-log rows** — one row per playbook step a run measured, carrying its
  `acted`, `override_reason`, and `evidence_ref`.
- **Interventions** — when a human intervened in each session of the window,
  read through `step_order.py` over the local transcripts (`--transcripts-dir`,
  capped by `--max-sessions`, default 25).
- **Stated purposes** — every registered skill's and hook's own description,
  paired up and put to the `lifecycle-overlap` llm-judge channel, which answers
  whether two rules say the same thing or one already covers the other.

## The proposal rules

Each rule needs its own evidence. The thresholds are the command's own flags,
and the level thresholds fall back to `[thresholds]` in
`engine/hooks/hooks.toml` when no flag is given.

| Class | Rule | Threshold |
| --- | --- | --- |
| `retire` | All three: no skill-use row on any harness inside the window, no owned cluster, and every hook that cites the skill silent. A skill the structural-wins list names is recorded as a `structural-win` instead. | window `--window-days 60`; list at `--structural-wins` |
| `rework` | A playbook step skipped with a reason, or a gate overridden in more than half of at least ten measured runs. | `--rework-min-skips 1`, `--rework-min-runs 10`, `--rework-override-rate 0.5` |
| `move-earlier` | An intervention landed after a step whose `evidence_ref` an earlier step of the same playbook already recorded. | one occurrence |
| `strengthen` / `weaken` / `simplify` | The hook runner's own per-rule suggestion: "warn to stop" is a strengthen, "stop to warn" a weaken, "review or turn off" a simplify. | `--min-closed-findings 30`, `--promote-max-ignore-rate 0.02`, `--demote-min-ignore-rate 0.10`, `--review-min-ignore-rate 0.50`, `--review-min-unchecked-rate 0.05` |
| `combine` | The judge answered `hit` on a pair of stated purposes. | pairs ordered by shared words, `--max-judge-pairs 120`, walked with `--judge-skip-pairs` |

A mined cluster with no owner in the table is its own `coverage-gap` class —
nothing to change yet, a rule that does not exist.

Each class becomes **at most one** proposal, written under the report's
`proposals/` folder, titled with the `[auto]` prefix and carrying its base and
head counts in the house PR schema. `--open-prs` hands those bodies to a draft
pull request, skipping a class that already has one open.

## The three outcomes

The pass ends in exactly one outcome, printed first with its reason:

| Outcome | Exit | Means |
| --- | --- | --- |
| `clean` | 0 | No class fired over the window. |
| `changed` | 1 | At least one proposal was written. |
| `blocked` | 2 | A source could not be read at all, a judged pair came back `unchecked`, or a write failed. |

A blocked pass proposes nothing — a signal it could not read is not a signal
that found nothing. A partial read inside one session, and a pair the pair cap
left unjudged, are reported as their own `note` and `overlap-capped` rows with
their counts printed, and are never counted as clean.

## Never merge

The pass reads records and writes only its own report and its proposals. It
never edits a live skill, hook, or playbook, and it never merges. Every
proposal body says so in its Non-goals, and its Revert Plan is "close this
proposal" — nothing was applied, so there is nothing to revert. A person reads
the proposal and decides; the pull request is the gate, the same way the
headless mine path treats GitHub review as the gate — see
[session-mine.md](session-mine.md).

## Tests

```bash
python3 engine/skills/reflect/scripts/tests/test_lifecycle.py
```
