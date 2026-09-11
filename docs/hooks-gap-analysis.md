# Hooks gap analysis: user interventions that should be hooks

The ask: every place the user had to step in by hand should, where a
mechanical check can catch it, become a hook rather than a prose rule.

Evidence: two real sessions in the same project, one Cursor (375 human
turns, 86 frustration-flagged, `intervention-must-automate: yes`) and one
Claude Code (32 human turns, 25 of them followed by a `diu-stop` block).
Counts below come from `engine/skills/reflect/scripts/token_audit.py` plus a
backtest of each candidate hook against those transcripts. Transcript text
was classified, never copied.

Tiers follow the reflect fix hierarchy in
[`engine/skills/reflect/references/lenses.md`](../engine/skills/reflect/references/lenses.md):
1 categorical, 2 lint/test, 3 hook, 4 prose, 5 human review.

## Gap table

| Class | What the user had to do | Existing cover | Verdict | Cheapest tier |
| --- | --- | --- | --- | --- |
| A. invent-under-prohibition | Told the agent not to fabricate values; it did anyway; escalated to all-caps | none that sees values | **Not a catstack hook.** Whether a number was invented needs the data source; only the product repo can check it. Tier 1 in the product: an export gate that fails any row without a source citation. Catstack covers the *repeat* of the prohibition (class C). | 1 (product) |
| B. done/PASS without proof | Asked "did you run it?" after bare "tests pass" / "fixed" | `diu-stop` (banned openers, causal claims), `prove-it-ship-gate` (live nouns only), `wrong-check-reflect` (after the retraction) | **GAP, built: `named-verb-guard`.** Stop hook. Trigger: the user's last message named test / repro / run / rerun / regenerate / prove / show / delete / revert / a short "stop". Rule: the reply must carry a closed fenced block or `path:line` (URL or table row also count for run / regenerate / show; a delete command this turn for delete / revert; no mutating tool calls for stop). Guards: imperative position only, a well-formed `{{CAT-UNVERIFIED}}` tag or a question always passes, hook-feedback lines are not the user. Blocking. | 3 |
| C. restated constraint | Re-typed "stock-agnostic" three times, "one parser per form type", lookback semantics | `frustration-watchdog` (only verbatim re-sends within 10 min) | **GAP, built: `restated-constraint`.** UserPromptSubmit hook. Trigger: prompt carries must / never / always / don't / one-X-per-Y / again / I told you, and an earlier human message shares a hyphenated term, the same constraint clause, or is a near-duplicate. Injects "already named at turn N, FAIL class, apply before replying". Guards: generic hyphen words (`to-do`, `follow-up`) never match; a prompt re-sent 3+ times is a template, not a correction; the transcript's own copy of the current prompt is skipped. Advisory. | 3 |
| D. proof polling | "prove it" / "show me" / "are you sure" repeated (7 times) because rows carried no citation | none | **Folded into `named-verb-guard`.** Second proof demand in a session requires a fenced block, `path:line`, or URL in the reply. Same evidence parser, so one hook instead of two. | 3 |
| E. hook feedback counted as the user | `frustration-watchdog` read `Stop hook feedback:` lines as human turns | `frustration-watchdog` | **Fixed in place.** Hook-feedback prefixes join the injected-line skip list; a verbatim re-send is no longer pushed out of the 8-message window by nine diu blocks. | 3 |
| F. brevity blocks on analysis answers | `diu-stop` blocked 25 of 32 Claude turns (150 to 476 words on finance questions) | `diu-stop` | **No new hook.** The hook is doing its job; whether 150 words is the right cap for research answers is a tuning question (`WORD_LIMIT`), not a gap. | 3 (exists) |
| G. invented principles | "you just invented principles that had no basis in the transcript" | `check_skill_test_coverage` (a fires example must exist) | **Cannot be a hook.** Whether a mined rule is grounded needs the reviewer to read the transcript. Tier 5; the reflect skill already demands a quote per finding. | 5 |
| H. user-side macro re-sends | 59 of 78 verbatim repeats were two workflow prompts the user re-sent 33 and 26 times | `token_audit.py` counts them as `verbatim-repeat` | **Not a hook; an audit false positive.** The audit should split "same text re-sent to poke the agent" from "same text used as a template". Filed here, not built. | 2 (audit test) |

## Backtest of the built hooks

| Hook | Cursor session | Claude session |
| --- | --- | --- |
| `restated-constraint` | 12 fires on 375 turns; includes the three `stock-agnostic` restatements (turns 155 and 176 point back to 154 and 155) and two runs of back-to-back restatements | 0 fires on 32 turns |
| `named-verb-guard` | 16 turns named a verb or polled for proof; 12 replies carried no evidence and would have been blocked (prove x4, rerun x4, show x2, test, run) | 3 turns named a verb; 0 blocks (each reply carried a fence, sha, or URL) |
| `frustration-watchdog` fix | not re-run | 25 `Stop hook feedback:` lines were previously counted as human turns |

## What was deliberately not built

- **`no-invent-guard`** (class A). A generic shape would be "numbers in the
  reply that appear in no tool output this turn", which flags every derived
  figure. The categorical fix is an export gate in the product repo.
- **Cursor and Codex wiring** for the two new hooks. Cursor's
  `beforeSubmitPrompt` cannot inject context, so `restated-constraint` there
  needs the `build-the-lever` state-then-postToolUse pattern; `named-verb-guard`
  needs a Cursor `stop` followup. Both are follow-ups, same as
  `frustration-watchdog` and `prove-it-ship-gate` today.
- **A `diu-stop` cap change** (class F). Tuning, not a gap.
- **Audit split for template re-sends** (class H). A `token_audit.py` change
  with its own test, out of scope for a hooks slice.
