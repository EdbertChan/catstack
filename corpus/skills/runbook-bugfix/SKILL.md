---
name: runbook-bugfix
description: >-
  Work a reported bug as a routed procedure: reproduce it on the surface it
  was reported on, binary-search the cause with the history read first, plan
  the smallest fix the evidence justifies, verify on the original failure,
  then stage the repro before the fix and open the pull request. Use when
  asked to fix a bug, chase a regression, or find why something broke.
  Imported from pstack's poteto-mode bug-fix playbook at upstream
  commit-ce649c03ac3b75b6ae80cbd15b7e2c536caedb5a, with its `architect`,
  `tdd` and control-skill citations dropped because this repo ships no such
  skills, and each remaining step rebound to a rule id in
  engine/runbook/rules.tsv.
playbook-trigger: fix the bug
---

# runbook-bugfix

Use this the moment a bug report arrives, before the first edit. The
procedure is routed data: the `playbook-router` hook injects the numbered
step lines into the turn, and the generic `runbook-gate` hook records how
each one ended.

## Why this exists

A bug fix is the task type this repo already has the densest rule coverage
for, and the rules fire one at a time, after the fact. Routing them as one
ordered procedure puts them in front of the work instead of behind it: the
repro comes before the hypothesis, the history comes before the blame, and
the smallest fix comes before the belt-and-suspenders one.

## The playbook

Open [playbooks/bugfix.md](playbooks/bugfix.md) and work its eight steps top
to bottom. Each heading carries its own binding in brackets — the rule id it
compiles from, its level, and, where a harness event can see it, the evidence
key and the event.

## Invariants (assert)

- The repro runs first and on the reported surface. A unit test shows branch
  behaviour, not bug absence, so it is never the repro.
- Every shipped line traces to runtime evidence. A change that "might help"
  is a hypothesis; when the evidence refutes it, revert what it motivated.
- Verification lands on the original failure. Inconclusive and wrong-surface
  are both reported as failures, never as a pass.
- The failing repro is committed before the fix, so history reads as the bug
  then its cure.
- `enforcement_profile` is `guided`, so an unproven hard step blocks a done
  claim while soft and conditional steps remain measured. A step that does
  not apply is written out as `skip: <step number> <reason>` rather than
  dropped.

## Do not

- Ask the person who reported the bug to reproduce it for you until the
  reproduction has been driven as far as it goes and the specific reason the
  local surface cannot reach it is written down.
- Name a commit as the cause before its history is read.
- Keep retrying the same failing command. The third identical error is the
  signal to cut the scope, not to try once more.
