---
name: create-playbook
description: >-
  Write a new playbook for a task type: one numbered step per line, each
  bound to a rule id the repo already ships, each step's enforcement level
  chosen from what a harness event can actually see. Use when asked to
  create or add a playbook, turn a repeated correction into a routed
  procedure, or author a `playbooks/*.md` file the playbook-router injects.
---

# create-playbook

Use this before writing any file under a `playbooks/` directory. A playbook
is routed data, not prose: the `playbook-router` hook injects its numbered
headings into the next turn, and `scripts/runbook/check_playbook.py` rejects
a step that names no rule.

## Why this exists

One front door keeps every playbook the same shape. Hand-written playbooks
drift in three ways that all break the same way: a step that names no rule
id, so nothing can check it; a step declared `hard` with no harness event
able to see its evidence, so the level is a wish; and a trigger phrase
already claimed by another installed playbook, so neither routes.

## The playbook

Open [playbooks/create-playbook.md](playbooks/create-playbook.md) and work
its eight steps top to bottom. Each heading carries its own binding in
brackets — the rule id it compiles from, its level, and the evidence key and
harness event that can see it.

## Invariants (assert)

- Every step is one line `## N. Title [rule-id · level · evidence: key · @event]`,
  and every rule id comes from `engine/runbook/rules.tsv`. No invented ids.
- A step is `hard` or `conditional` only when a harness event can see its
  evidence key. Nothing can see it, so it is `soft`.
- Hard and conditional steps bind to the generic runbook gate. One new hook
  per playbook is the thing this skill exists to prevent; call the
  `ship-a-detector` skill only when a new evidence key needs a detector.
- A playbook ships with its fixture pair under the skill's `tests/` dir —
  one prompt that routes, one that stays silent — before it is installed.
- `python3 scripts/runbook/check_playbook.py <path>` exits 0 before the PR
  is opened. Exit 2 is unchecked, never a pass.

## Do not

- Write a `## Steps` section into `SKILL.md`. A skill's own numbered
  document sections never route; the procedure lives in `playbooks/`.
- Add a second procedure file to one `playbooks/` dir. The router then
  cannot tell which one is the skill's, and the skill routes nothing.
- Declare `strict` to sound serious. The profile describes what the gate
  does with a breach, not how much the author cares.
