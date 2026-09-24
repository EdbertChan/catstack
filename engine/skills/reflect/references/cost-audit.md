# Cost audit

Read this when running reflect step 2. Do not hand the raw JSONL to a lens — run the script, hand its small output (or `--out` JSON) to the Cost lens.

## Commands

```
python3 skills/reflect/scripts/token_audit.py claude <path-to-session.jsonl>
python3 skills/reflect/scripts/token_audit.py claude <path-to-session.jsonl> --out /tmp/audit.json
python3 skills/reflect/scripts/token_audit.py claude <path-to-session.jsonl> --no-subagents
python3 skills/reflect/scripts/token_audit.py claude <path-to-session.jsonl> --judge
python3 skills/reflect/scripts/token_audit.py omp    <path-to-omp-session.jsonl> --out /tmp/audit.json
python3 skills/reflect/scripts/token_audit.py codex  <path-to-rollout.jsonl>
python3 skills/reflect/scripts/token_audit.py codex  <path-to-rollout.jsonl> --out /tmp/audit.json
python3 skills/reflect/scripts/token_audit.py omp    <path-to-omp-session.jsonl>
python3 skills/reflect/scripts/token_audit.py cursor <path-to-agent-transcript.jsonl>
python3 skills/reflect/scripts/token_audit.py remotes   # names only, from ~/.invoker/config.json if present
```

Prefer `--out <path>` when feeding lenses: it writes a JSON report of named yes/no flags with rationales. Codex output includes human-intervention flags plus same-problem thrash flags that can be recovered from rollout tool-call history; it does not yet include Claude's redundant-read or model-tier candidates. Stdout stays a short summary (path + flag lines). Progress/errors go to stderr. Without `--out`, stdout is the full prose report (legacy; existing tests use this).

It reports, per session: total tokens by category and cache-read share, turns whose only tool calls were Read/Grep/Glob (model-tier downgrade candidates), redundant re-reads of an unchanged file, tool errors, cache-creation spikes (a fresh multi-hundred-KB cache write mid-session, instead of a cache read, usually means context got dropped/rebuilt rather than genuinely new information arriving — worth checking what preceded it), and per-turn token growth (a session where each successive turn costs more than the last, because the whole growing history gets resent every turn, burns quota fast even at a high cache-hit rate — this is the main thing to check when a session "ran out" quickly).

## Fleet spend dashboard

For "where is the money going across all my sessions", not one session, build the ledger and render the page:

```
python3 engine/skills/reflect/scripts/spend_ledger.py fleet --days 30 --out /tmp/ledger.json
python3 engine/skills/reflect/scripts/render_spend_report.py /tmp/ledger.json --out /tmp/agent-spend.html
```

`fleet` scans this machine, then pipes the same script over ssh to every `remoteTargets` host in `~/.invoker/config.json`; only per-session numbers come back. Each session is priced at list rates (Codex as an estimate), tagged by who started it (typed / invoker / scripted / eval), and carries its helper-agent cost and the cost of calls that only waited or re-ran a command already run five or more times. A host that cannot be reached is listed as not scanned on the page, and tokens with no model are shown as unpriced rather than dropped. Publish the HTML as an artifact when the user wants a shareable page.

## Subagents are part of the session

`claude` mode also loads `<session-dir>/subagents/agent-*.jsonl` (resolved the same way `subagent_cost.py` does) and reports them under a `subagents` section: count, tokens by category, the top 5 agents by tokens with their `meta.json` description, and the thrash found inside them (redundant reads, tool errors, recurring failure signatures, longest no-verify edit streak, self-retractions), plus a `subagent-thrash` flag naming which agent files fired. `totals.combined_total` is own + subagent tokens; `totals.total` stays the parent's own spend so older comparisons still line up. Subagent `user` rows are the parent's prompts, so they never feed `frustration-signals` / `intervention-must-automate` — the section's `human_messages` is expected to be 0. `--no-subagents` opts out. Hand the whole report to the Cost and Judgment lenses: a parent that looks clean can still have burned its budget, or repeated a failure, inside a delegated agent.

The additive `context_cost` section is a token-only, fixture-backed measurement contract. It reports `parent_spend`, `child_spend`, `child_output`, `child_cache_read`, `child_cache_creation`, `child_count`, `child_turns`, aggregate `bash_turns`/`non_bash_turns`, and the first child trigger as `first_trigger_text`; each `children` row retains its own trigger and dimensions. It reuses message-id deduplication and subagent directory resolution, and never estimates provider dollars. The standalone `subagent_cost.py` CLI prints the same fields under `Subagent context-cost eval`.

## Frustration signals

Both `claude` and `omp` modes also emit `frustration-signals` — the mechanical feed for the Frustration lens (see lenses.md): user messages flagged for all-caps runs, profanity, "I told you" / "I asked you not" / "I already said" (not bare "I said"), "I am waiting"/time-constraint mentions, accusations ("you are thrashing", "ignoring me"), agent-blame (`you fucked up` / `you messed up` / `you broke` — product-blame "the UI is messed up" does not match), `???`, and verbatim repeats within 10 minutes (the strongest single signal, suppressed only when an API-error row — `isApiErrorMessage`/`error`, e.g. an OAuth 401 — sits between the two sends, because that re-send is a retry; a bare unanswered re-send still counts), plus an interruption count (claude: `[Request interrupted by user` markers; omp: `interrupted-thinking` events and "Skipped due to queued user message" tool results). Human messages only — claude-mode system-injected user turns (`<command-…>`, `<task-notification>`, `<teammate-message>` relays from peer agents, continuation summaries, skill injections) are excluded; counting them poisons the stats, found on a real 124MB transcript where task-notifications echoing the word "thrashing" inflated the count from 139 to 151. Backtested against the session that motivated it: 13/58 messages flagged, matching the hand audit.

They also emit `brevity-hook-blocks`: how many replies the brevity checker itself stopped, read from the Stop-hook blocks the harness writes into the transcript as user rows. Those rows are the checker speaking, not the person, so they are excluded from every human count, including `brevity-follow-ups` and the tone counts. Read the two together: blocks with no follow-up means the checker caught the long reply before the user had to; a follow-up means it did not. Harnesses that do not record hook blocks report `unchecked`.

They also emit `brevity-follow-ups`: how many times the user had to ask for a shorter reply, counting `/diu` invocations (read from the command-name field, not matched out of prose) plus messages whose whole text is `eli5` / `eli 5`. This is the feed for judging whether the always-on brevity rule is working: a session where the user asked twice is a session where the default reply was too long twice. Codex, OMP, and Cursor transcripts carry no slash-command field, so those modes count the `eli5`-only messages and report `unchecked` when that count is zero — a zero there is not a clean count. `/diu` mentioned inside a longer sentence is not a request; only the typed command is.

They also emit `intervention-must-automate`: yes when a verbatim re-send fired, any intervention kind (`told-you`, `accusation`, `agent-blame`) appears ≥2 times, or ≥2 distinct intervention kinds appear in the session. One "I told you" is frustration only; the same class twice is FAIL and must route to `automate-me`. `/loop` polls and Stop-hook injection text are not the human complaining.

Two more kinds count, both read from human messages only. `restated-after-rejection` is the person's next message after a tool call they rejected; the rejection comes from the harness's typed denial fields (`toolDenialKind: user-rejected`, `toolUseResult: User rejected tool use`), never from tool_result prose. `restated-rule` is a message that restates a rule, skill, or standing decision that already exists; its meaning is decided by the llm-judge against the `engine/hooks/llm-judge/phrases/restated-rule.json` dictionary, and only under `--judge`. Grow that dictionary from real misses (`phrase-judge`), never a regex. Without `--judge`, or when no judge runner answers, `intervention-must-automate` reports `unchecked` unless other evidence already makes it `yes`.

To re-run the reality check after tuning the detector, use the shared runner `scripts/test/backtest_detector.py` from the repo root:

```
python3 scripts/test/backtest_detector.py --detector engine/skills/reflect/scripts/token_audit.py:replay_frustration --unit rows [--limit N] [--verbose] [paths...]
python3 scripts/test/backtest_detector.py --detector engine/skills/reflect/scripts/token_audit.py:replay_frustration --unit rows --compare main
```

It sweeps the newest N (default 5) local Claude/OMP transcripts, or explicit paths, and prints one hits/kinds summary line per session, then the totals, hit rate, and a sample of flagged messages. `--compare <ref>` replays the same transcripts through the detector at that git revision and lists the messages the change newly flags and newly misses — what a widening change has to justify. The committed half is the runner and `replay_frustration()`; the transcript data itself stays local.

## Same-problem thrash

A session can be stuck on one problem while every tool call is technically distinct — each Edit is different text, so the exact-duplicate detector above sees nothing. `token_audit.py` (Claude mode) also flags two shapes of this, both heuristic: (1) **recurring failure signatures** — tool errors whose text repeats (numbers normalized out) across more than one attempt, meaning the same failure keeps recurring rather than getting fixed; genuine user tool-rejections are excluded, since those are the user redirecting, not the agent failing; (2) **edit streaks without a verification run in between** — three or more `Edit`/`Write` calls to the same file with no intervening `Bash` call shaped like a test/build/lint/typecheck command, meaning the agent kept changing code without checking any of the changes. Both point at the same root cause: no fast feedback loop. Feed these counts to the Judgment lens (step 3) alongside the cost numbers.

## Cross-machine remotes

Other machines this user runs agents on are listed (by name only, never by host/IP) in `~/.invoker/config.json` under `remoteTargets`, if that file exists. `token_audit.py remotes` surfaces which target names *could* be scanned over SSH. It never SSHes itself — actually reaching into a remote machine is a separate, explicitly-confirmed step. A confirmation to scan remote hosts, given before the exact command exists, authorizes the *scope*, not the *payload* — before fanning a script out over SSH to N hosts, show the exact command or script once so the user has actually seen what ran.

## Tails, not averages

Real waste concentrates in a handful of outlier sessions. Before (or alongside) auditing the session at hand, run `python3 skills/reflect/scripts/top_sessions.py [N]` — it scans every local Claude/Codex/OMP session (Cursor excluded, no token data there) and ranks them by total tokens. Investigate the top few with `token_audit.py claude|codex|omp <path>` before spending review time on an average session. Don't silently cap this to "top 5 and done" — say how many sessions were scanned and how many were outliers worth a look.

`top_sessions.py`'s ranking is still a **triage signal, not a final dollar figure** — a fast, no-cost-model raw token sum. Good enough to say "look here first," not a substitute for `token_audit.py`'s fuller output on whatever it flags.

A corpus-wide `top_sessions.py` pass is what actually surfaced a real, multi-week cross-session thrash pattern that a targeted keyword search alone would have missed — confirming evidence for the "periodically worth doing by hand" cadence, not a reason to add a cron.

## Model-tier backtest

`model_tier_savings()` in `token_audit.py` prices the flagged lookup-only turns' output tokens at the session's actual model vs. `claude-haiku-4-5`, using published list prices (`PRICING` dict in the script) — a real, reproducible dollar figure, not a guess. It only prices the output side, so treat it as a lower bound and say so. This does not verify a cheaper model would have produced the *same result* — that would require actually re-running the turn. If the user wants that verified, say so explicitly rather than implying the $ figure proves equivalence.

## Tests

`skills/reflect/scripts/tests/test_token_audit.py` covers the dedup fix (the single most important correctness property — get it wrong and every total is inflated 2-3x), redundant-read detection, error detection, the two same-problem-thrash detectors, the savings calculation, `--out` flag objects, and both scripts' per-tool scan functions, using small synthetic fixtures (never real user transcripts). Extend that file — don't create additional unit-test files — when adding new detection logic.

`skills/reflect/scripts/tests/test_e2e_sample_conversations.py` runs the real `token_audit.py` CLI against committed sample conversations under `fixtures/` (clean / thrash / lookup-heavy) and asserts the Cost-lens flag recommendations end-to-end. Regenerate fixtures with `python3 skills/reflect/scripts/tests/fixtures/generate_sample_conversations.py`.

Run either with `python3 -m unittest discover -s skills/reflect/scripts/tests -v`.
