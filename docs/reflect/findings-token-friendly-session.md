# Reflect findings: token-friendly reflect planning session

Findings list for the reflect pass whose Accepted items the linked pull request applies. Step 7 of the reflect skill allows this list to live in a file committed on the PR branch and linked from the body.

Source: the session's reflect output (lens reports and the audit JSON). Evidence pointers name the lens or audit field that holds the detail.

### Edits applied

- `engine/skills/reflect/references/cost-audit.md` — one paragraph at the end of Model-tier backtest: rank waste removal (re-reads, retries, extra turns, duplicate passes) above fidelity cuts (fewer lenses, cheaper model, digests); a declined run of recommendations is itself a finding to say aloud. Why: a menu of fidelity cuts each marked recommended, with every one declined, reads as separate decisions unless the preference behind them is named. Evidence: Judgment, Divergent and Frustration lens reports. Catch: Backlog B2 hook; hand backtest on the session's menu answer -> `fired`. Grounding: no known prior art.
- `engine/skills/reflect/references/lenses.md` — Reviewer prompt hygiene: when no tracked files were touched, the History file list comes from the files the plan targets (plan paths, owning-file columns); the lens is skipped only when that list is also empty. Why: a planning session edits an untracked plan while naming every file the plan will touch, and the History lens can still read those files; the old sentence told it to skip. Evidence: History lens report. Catch: none — the parent assembles the file list in prose and no script builds it; B11's CLI is the place to pin it. Grounding: no known prior art.

### Backlogged

- B1 (tier 3 hook): a Stop hook that blocks when a queued human message arrives mid-turn and no later assistant text names it, because existing prose on ambiguous follow-ups does not hold on its own; evidence: Judgment, Divergent and Frustration lens reports.
- B2 (tier 3 hook): a sibling of answer-overrides-menu that fires when every menu answer differs from its recommended label and injects "all recommendations declined; state the preference this reveals"; evidence: Judgment lens report.
- B3 (tier 1, fallback tier 3, plus tier 2): set the zsh options that stop a bare `=word` or an unmatched glob from aborting the whole command, guarded to the agent shell by its `CLAUDECODE=1` variable, with a PreToolUse warning as fallback and a `details` list on the audit's recurring-failure-signatures flag; evidence: Tooling and Cost lens reports, reproduced in the pass.
- B4 (tier 2 lever plus lint): a plan-chain renderer that uses a real YAML dumper and runs the plan lints itself, plus a lint that rejects temp-dir and scratchpad paths in plan files and memory notes; evidence: Tooling and Judgment lens reports.
- B5 (tier 2 test): make the audit classify lookup-shaped shell reads per turn and report `unchecked` when any exist, instead of a session-wide bash-only switch that reports clean once any Write occurs; evidence: Cost lens report.
- B6 (tier 3): attach the ready rewrite that the brevity hook already has to its block, so a blocked reply does not cost retry turns; evidence: Cost and Frustration lens reports.
- B7 (tier 3): make every deny message say that nothing was written or run, with a test over every deny string, so the next call does not assume the file exists; evidence: Tooling lens report.
- B8 (tier 3): give the wakeup hook a hint table from poll commands to their native waiters, count repeats only after a run that exited 0, and name query loops in the event-wait skill description; evidence: Tooling and Judgment lens reports.
- B9 (tier 2 test): extend the one-reader test's walk to the skill script folders so a direct environment read inside a skill script is caught; evidence: History lens report.
- B10 (tier 2 test): decide lesson-route overlap by meaning or within one sentence rather than by two shared short words, with a test that an unrelated quote is not already-covered; evidence: this pass's own lesson-route output.
- B11 (tier 1 CLI plus tier 2 test): a fanout-complete flag that prints the lens plan from the audit JSON, a test that the field the skill text names exists in the audit output, and the matching skill-text fix; evidence: the pass's own process notes.
- B12 (tier 1): have each lens write its report to a file and return a one-line pointer, with fanout-complete checking file presence and size, so a Stop-time trailer cannot replace the report; evidence: the pass's own process notes and the attribution hook's warn mode in `engine/hooks/hooks.toml`.
- B13 (tier 3 hook): a Stop hook that warns when the session wrote under `plans/` and none of it is tracked, since the plan-first skill text carries no commit-the-plan rule; evidence: Divergent lens report.
- B14 (tier 2 lint): a claims-absent check in the skill file-refs gate for skill text that says a tool is missing while the core rules require it; evidence: History lens report.
- B15 (tier 2): reflect step 7 requires the findings list in the PR body while make-pr's description_check bans statements about the repo's past from PR bodies, and the judge gave different hits on identical input across runs; fix at tier 2: description_check exempts a section headed '## Reflect findings', or reflect step 7 writes this docs file by default; evidence: seven judge runs on one body in this apply.

### Routed to automate-me

- none — no candidate returned bucket `automate-me`.

### Dropped

- D4 label kept, mechanism swapped: a judgment call inside one plan with no mechanical catch; the lesson-route overlap that covered it is B10.
- History lens items 2 and 3: inputs for the plan file, not session lessons.
- The no-verify edit streak and the cache-creation spike after a long idle: markdown has no test, and the idle rewrite falls under the existing session-hygiene rule.
- Two one-off path and shape guesses from the Tooling lens.
- Queued steer and the asking style as new prose: existing rules already say both; the mechanical halves are B1 and B2.
- Brevity blocks as a lesson: the brevity hook already automates it; mechanics in B6.

### Cost audit

Command: `python3 engine/skills/reflect/scripts/token_audit.py claude <session.jsonl> --out audit.json`. Output, pasted:

```
total 12,328,335 tokens (combined 12,531,335), cache-read share 95.3%
flagged thrash/model-tier items 3 (recurring-failure-signatures=1, no-verify-edit-streak=3, cache-creation-spikes=1; model-tier-candidates=0, redundant-reads=0)
intervention-must-automate: no
```

### Reflect pass cost

Command: `python3 engine/skills/reflect/scripts/subagent_cost.py --reflect <session-dir>`. Output, pasted:

```
Reflect pass cost: 9 agents, 11,132,890 tokens (orchestrator 5,113,565/32, lenses 3,662,445/47, synthesis 937,217/10, apply 1,419,663/14)
```

### Feedback-loop check

See the `recurring-failure-signatures` and `no-verify-edit-streak` fields in the Cost audit output above. The first maps to B3; the second to the plan-file streak in Dropped.

### Open questions

- B3: add `setopt NO_EQUALS NO_NOMATCH SH_WORD_SPLIT` to the zsh profile under a `CLAUDECODE=1` guard, so the agent shell stops aborting on `=word` and unmatched globs while the interactive shell keeps its defaults — yes or no?
