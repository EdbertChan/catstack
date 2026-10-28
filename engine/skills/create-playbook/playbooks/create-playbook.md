---
runbook: create-playbook
version: 1
applies_to:
  - engine/skills/
  - corpus/skills/
  - product/skills/
compiled_from:
  - playbook-router
  - principle-bind-to-named-inventory
  - principle-report-the-disqualifier
  - ship-a-detector
  - create-skill
  - principle-prove-it
  - prove-it-ship-gate
  - make-pr
playbook-trigger: create playbook
enforcement_profile: guided
---

# Writing a playbook for one task type

Work the eight steps below in order. Each heading carries its own binding:
the rule id it compiles from, its level, and the evidence key and harness
event that can see it. The headings are what the router injects.

## 1. Name the task type and its trigger phrase [playbook-router · hard · evidence: router_trigger_free · @UserPromptSubmit]

Write down the task type in one sentence and the phrase a person would type.
Run the router against that phrase and confirm no installed playbook already
answers it; a phrase two playbooks claim routes neither.

## 2. Write one line per step, each bound to a rule id [principle-bind-to-named-inventory · hard · evidence: step_rule_binding · @PreToolUse]

One step is one line, titled and bound: `## N. Title [rule-id · level]`.
Every rule id comes from `engine/runbook/rules.tsv`. Nine steps is the cap,
and a three-line body is the cap under each.

## 3. Pick each step's level from what an event can see [principle-report-the-disqualifier · soft]

Hard means the gate refuses; conditional means it refuses when the condition
holds; soft means it only tells you. Drop a step to soft when no harness
event can see its evidence, rather than declaring a check nothing can run.

## 4. Bind hard and conditional steps to the generic runbook gate [ship-a-detector · conditional · evidence: new_evidence_key · @PreToolUse]

The one generic gate reads every binding, so a playbook needs no hook of its
own. Call `ship-a-detector` only when a step needs an evidence key no
detector produces yet, and name that key here.

## 5. Write the fixture pair before installing [create-skill · hard · evidence: prose_fixture_pair · @Stop]

Write `tests/fires_example.md` with a prompt that must route, and
`tests/stays_silent_example.md` with a near neighbour that must not. Each
says in one paragraph why it lands on that side.

## 6. Run the playbook validator [principle-prove-it · hard · evidence: check_playbook_exit · @Stop]

Run `python3 scripts/runbook/check_playbook.py <path>` and paste its output.
Exit 1 names the file and step to fix. Exit 2 is unchecked — an input it
could not read — and is never reported as a pass.

## 7. Route the fixture prompt and paste the injected steps [prove-it-ship-gate · hard · evidence: injected_steps_pasted · @Stop]

Feed the `fires_example.md` prompt through `engine/hooks/playbook-router/detect.py`
and paste the injected steps. Feed the silent fixture through the same path
and show that it injects nothing.

## 8. Install across four harnesses, then open the pull request [make-pr · hard · evidence: pull_request_url · @Stop]

Register the skill in `skills.toml` and run `./install.sh`, or
`bash scripts/link_skill_three_harnesses.sh <dir>` for a project skill, so
Claude, Cursor, Codex and Muse all get it. Then call the `make-pr` skill.
