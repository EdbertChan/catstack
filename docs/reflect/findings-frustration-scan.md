# Reflect findings: frustration across one day of sessions

Findings list for a corpus-wide reflect pass over this machine's human Claude Code sessions in a 24-hour window, run after the user said the sessions had gone badly and asked why. Step 7 of the reflect skill allows this list to live in a file committed on the PR branch. Nothing was applied: Accepted is empty.

Source: the review agent's hand-back (lens reports plus audit JSON). Quotes are bounded and paraphrased; session ids are the first eight characters. Lines marked `{{CAT-UNVERIFIED: ...}}` were not re-opened by the parent.

### Top three recurring patterns

1. The agent answered a different question than the one asked. Stated constraints were dropped: build only one target on remote execution and the rest locally; no right-click step; replace the old job rather than add a new one; run it locally. The agent offered the remote box, a right-click, or a job that does nothing. Evidence: sessions 47d781af, 37ec1f53, d4ff17e6, d8d50f4f.
2. The rules only warn. The repeat-detector and named-verb hooks are in warn mode, so the agent read the warning and changed nothing, while the brevity hook squeezed answers until they were thin or turned into a question (d4ff17e6, just before the user's loudest message).
3. The agent pasted proof but skipped the point. It showed command output without saying whether the step worked (37ec1f53), and it reported numbers without saying how they were obtained (1dce81c4, 2a312e85, 2b990c47).

### Edits applied

None. Accepted is empty: every finding that passed the lesson-route gate has a hook-tier fix, so it sits in Backlog.

### Backlogged

- B1 (tier 3 hook): promote the restated-constraint hook from warn to stop on all-caps, profanity, or a verbatim repeated message; the next reply must restate the constraint and the acceptance test first. Evidence: the hook fired in 37ec1f53, d4ff17e6, d8d50f4f (7 hits), 47d781af (6 hits) with no change in replies; `engine/hooks/hooks.toml` lines 154-155 (`named-verb-guard`) and 269-270 (`restated-constraint`) read `mode="warn"`, and `engine/hooks/restated-constraint/README.md:10` says "Advisory only. Never blocks." (read-confirmed at HEAD by the review agent). Catch backtest: the current hook `fired` but is non-binding; a promoted hook would stay `silent` on the first miss in d4ff17e6 (no caps or repeat yet) and fire on the second; reasoned trace only, `unchecked` by running. Grounding: forcing function, Norman, The Design of Everyday Things, 1988 {{CAT-UNVERIFIED: no checkable URL -- cannot verify: book not opened}}.
- B2 (tier 3 hook): the brevity hook fights substance. About 540 brevity blocks across six sessions (df436500 102, 1dce81c4 82, a2dbb519 82, d8d50f4f 62, d4ff17e6 60, 37ec1f53 44); 32 of 66 in d8d50f4f came from the single word "because" as an unverified-claim trigger. A compaction summary in d4ff17e6 recorded the cap as a standing user rule, so hook pressure became a fake user rule. Fix: split the hook's three jobs, drop the lone "because" trigger, nag once per term, cap consecutive blocks. Catch: fires every turn; cap backtest on d4ff17e6 `unchecked`. {{CAT-UNVERIFIED: hook internals -- cannot verify: no lens opened the hook source}}.
- B3 (tier 3 hook): compaction drops the end state. In d4ff17e6 the summary kept "hash-equivalent" and never said the new job had to replace the old one. Fix: a pre-compaction hook requiring a "done looks like" line that quotes the user's last stated objective. Catch: silent today (no such hook); backtest `unchecked`.
- B4 (tier 3): the user typed the cat-mode and prove-it commands by hand 38 times in 4 sessions (d4ff17e6 5, d8d50f4f 14, 37ec1f53 8, 47d781af 11). The default-on line is injected, so the skill loads; the loss is attention. Fix: a visible session-start confirmation and re-injection on repeat or impatience. Catch: silent today.
- B5 (tier 3): results reported with no method line, and long edit streaks with no verify (52 in 2b990c47, 45 in df436500, 17 in d8d50f4f). Fix: a pre-tool block on the Nth unverified edit and a method line beside benchmark numbers. Not run through the lesson-route gate. {{CAT-UNVERIFIED: no existing hook requires method disclosure -- cannot verify: engine/hooks was not searched}}.
- B6 (tier 3): sessions this long cost the most (df436500 about 662M tokens over about 1,379 turns; d8d50f4f about 337M over about 982 turns). Fix: a nudge near 300 turns or 100M tokens; session-hygiene prose already exists in `corpus/CLAUDE.learned.md`. The review lens's estimated saving is {{CAT-UNVERIFIED: saving -- cannot verify: assumes one extra turn per block}}.
- B7 (tier 3): an answer to a question should share words with it. In 37ec1f53 the user asked what was on the right-hand side and the agent replied with "I haven't confirmed yours is that one". Fix: a stop check on first-sentence overlap with the question; false-positive risk; catch `silent`, `unchecked`. Not run through the lesson-route gate.

### Routed to automate-me

None.

### Dropped

- R1, R2: dropped stated goal and "asked instead of acted", plus ignoring a stated place (the remote box offered four times after "do it locally"). Already covered; execution misses, not missing rules. Rules read at HEAD in `engine/CLAUDE.core.md`: line 11 (ambiguous referent), line 52 (simplest path under frustration), line 77 (persist through done), line 83 (literal question first). The cat-mode rule that a meaning question gets the meaning first was read in the installed bundle's working tree, not at HEAD. Enforcement lives in B1.
- R3: hook-noise counts (wait-needs-wakeup, unverified-tag-ledger, technical-writing-guard); fail the drift test and no one opened the hook internals.
- R4: duplicate-session suspicion between 1dce81c4 and a2dbb519, and model-tier savings of at most $0.0972 per session; not worth cutting first.
- R5: older spikes in cd495ece and 66c25275, outside the window and untraced.

### Cost audit

Scan: 807 sessions in the window, 778 automated judge runs ignored, 28 human sessions audited, 18 active in the window. In-window total 2,196,497,289 tokens, cache read 2,153,018,337 (98%). Largest: df436500 662,040,738; d8d50f4f 337,224,611; 1dce81c4 242,615,868; a2dbb519 242,463,534. d4ff17e6 alone 157,849,612; with 15 subagents 361,675,713.

Reflect pass cost (verbatim from `subagent_cost.py --reflect`): `Reflect pass cost: 8 agents, 13,271,868 tokens (orchestrator 9,175,471/62, lenses 3,775,953/46, synthesis 320,444/4, apply 0/0)`.

Lens turn targets (fanout-complete run, exit 0, "complete every expected lens returned"): Judgment 10/10, Tooling 6/10, Cost 5/6, History 7/12, Divergent 7/8, Frustration 11/8 over target. The Frustration lens reported 9 turns; the transcript count was 11; its reason was line indexing and shell quoting.

Feedback-loop check: longest no-verify edit streaks 52, 45, 17; recurring failure signatures d8d50f4f 10, df436500 13, d4ff17e6 4. Both non-zero.

### Citation confidence

Read-confirmed by the parent of the review agent: user messages in 37ec1f53, 47d781af, d4ff17e6 (line numbers within one or two of the audit's). Lens-reported only, name-matched: the hook-block counts, the 38 typed commands, the question-ending ratios, the History lens's commit references. Unchecked: one grep that failed (argument list too long), a few traced lines in df436500, whether subagent hand-backs were counted as user text, and every catch backtest (reasoned traces, none run). The firmware repo on the remote box was out of scope.

### Open question

Should B1 stop the reply on the first all-caps, profane, or repeated message, or only on the second? One yes/no settles the hook's threshold.
