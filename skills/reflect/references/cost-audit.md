# Cost audit

Read this when running reflect step 2. Do not hand the raw JSONL to a lens — run the script, hand its small output (or `--out` JSON) to the Cost lens.

## Commands

```
python3 skills/reflect/scripts/token_audit.py claude <path-to-session.jsonl>
python3 skills/reflect/scripts/token_audit.py claude <path-to-session.jsonl> --out /tmp/audit.json
python3 skills/reflect/scripts/token_audit.py codex  <path-to-rollout.jsonl>
python3 skills/reflect/scripts/token_audit.py omp    <path-to-omp-session.jsonl>
python3 skills/reflect/scripts/token_audit.py cursor <path-to-agent-transcript.jsonl>
python3 skills/reflect/scripts/token_audit.py remotes   # names only, from ~/.invoker/config.json if present
```

Prefer `--out <path>` when feeding lenses: it writes a JSON report of named yes/no flags with rationales. Stdout stays a short summary (path + flag lines). Progress/errors go to stderr. Without `--out`, stdout is the full prose report (legacy; existing tests use this).

It reports, per session: total tokens by category and cache-read share, turns whose only tool calls were Read/Grep/Glob (model-tier downgrade candidates), redundant re-reads of an unchanged file, tool errors, cache-creation spikes (a fresh multi-hundred-KB cache write mid-session, instead of a cache read, usually means context got dropped/rebuilt rather than genuinely new information arriving — worth checking what preceded it), and per-turn token growth (a session where each successive turn costs more than the last, because the whole growing history gets resent every turn, burns quota fast even at a high cache-hit rate — this is the main thing to check when a session "ran out" quickly).

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

`skills/reflect/scripts/tests/test_token_audit.py` covers the dedup fix (the single most important correctness property — get it wrong and every total is inflated 2-3x), redundant-read detection, error detection, the two same-problem-thrash detectors, the savings calculation, `--out` flag objects, and both scripts' per-tool scan functions, using small synthetic fixtures (never real user transcripts). Run with `python3 -m unittest discover -s skills/reflect/scripts/tests -v`. Extend that file — don't create additional test files — when adding new detection logic.
