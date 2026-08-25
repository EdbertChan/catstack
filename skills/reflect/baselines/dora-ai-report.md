# DORA-for-agents baseline report (v2)

**Captured:** 2026-08-25T03:17:18Z  
**File:** [`dora-ai.json`](./dora-ai.json)  
**Goal:** week over week / month over month, bad clocks go **down**; deploy frequency goes **up**. Do not commit a worse baseline.

## What these numbers mean (plain English)

| Clock | Question it answers | Better when |
| --- | --- | --- |
| **Lead** | After you say “go,” how fast does the agent start editing? | Lower |
| **Deploy frequency** | How many PRs merge per day? | Higher (also rises when you work more) |
| **MTTR** | After thrash, how long until a verify-ish recovery? | Lower |
| **Rework** | Of work we started, how often did we thrash or rewrite? | Lower |
| **Post-merge fail** | Reverts / hotfixes after merge | *Reported only* — we fix forward, so this stays ~0 and is **not gated** |

**Elite bars (targets, not the baseline itself):** lead &lt; 15m, deploy ≥ 2/day, MTTR &lt; 1h, rework &lt; 15%.

## Committed snapshot

### Last 7 days

| Metric | Value | Notes |
| --- | --- | --- |
| Lead (median) | **2 s** | 5 samples. Often a **fake clock** (line order when transcripts lack real timestamps). Do not treat as real planning time. |
| Deploy | **~14.3 / day** (100 merges) | Hit `gh search` cap of 100. Busy weeks look better. |
| MTTR (median) | **23 s** | 7 samples. Same timestamp caveats as lead. |
| Rework | **46.7%** (21 / 45) | **Main number to drive down.** Above elite (15%). |
| Post-merge fail | **0%** | Expected under fix-forward. Not gated. |

### Last 30 days

| Metric | Value | Notes |
| --- | --- | --- |
| Lead (median) | **2 s** | Same caveats. |
| Deploy | **~3.3 / day** (100 merges) | Same search cap spread over 30 days. |
| MTTR (median) | **~21 min** (1274 s) | 14 samples. |
| Rework | **71.8%** (61 / 85) | Higher than 7d — more rewrite clusters over a month. |
| Post-merge fail | **0%** | Not gated. |

## How rework is counted (v2)

A started execution “fails” (counts in the numerator) if **either**:

1. **Session thrash** — same flags as `reflect-on-thrash` (including `intervention-must-automate`), or  
2. **Git path-churn** — ≥3 commits within 24h that overlap the same path(s) (fix-forward rewrite / patch loops), optionally **paired** to a session via Write/Edit paths + workspace/cwd / `CATSTACK_DORA_GIT_ROOTS`.

```text
rework_rate = failed_executions / started_executions
```

One fail per `execution_id` (no double count if both thrash and rewrite fire).

This is why rework jumped vs v1 (~23%): v1 mostly saw session thrash; v2 also sees Invoker-style “patch the same files again” in git.

## What we mine

- Local Claude / Cursor / Codex sessions (capped)  
- Local `git log` on session workspace roots + `CATSTACK_DORA_GIT_ROOTS`  
- `gh` merged PRs (author=@me; merge count capped)

**Never committed:** transcript bodies, absolute session paths. Aggregates only.

## What “good” looks like from here

1. **Rework 7d and 30d go down** (skills/hooks that stop rewrite loops).  
2. Deploy can stay high or rise — do not “win” by merging less.  
3. Lead/MTTR stay secondary until wall-clock timestamps are real.  
4. Baseline updates require `check_dora_baseline.py --check-update` (every gated metric equal or better).

## How to refresh

```bash
export CATSTACK_DORA_GIT_ROOTS="$HOME/Documents/GitHub/catstack:$HOME/Documents/GitHub/Invoker"
python3 skills/reflect/scripts/capture_dora_baseline.py --out /tmp/dora-ai-new.json
python3 scripts/check_dora_baseline.py --current /tmp/dora-ai-new.json --check-update
# only then replace skills/reflect/baselines/dora-ai.json and update this report
```
