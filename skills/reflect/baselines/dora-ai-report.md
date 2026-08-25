# DORA-for-agents baseline report (v2)

**Captured:** 2026-08-24T12:00:00Z  
**File:** [`dora-ai.json`](./dora-ai.json) · **History:** [`dora-ai-history.json`](./dora-ai-history.json)  
**Goal:** week over week / month over month, bad clocks go **down**; deploy frequency goes **up**. Do not commit a worse baseline.

## Trends

Rework should fall over time (green dashed line = elite 15%).

History includes a **13-week as-of backfill** (sessions + git path-churn + `gh` merges).
Older weeks may show `deploy=0` because GitHub search only returns recent merges.
Tiny sample weeks can spike to 100% rework — read the line shape, not single-week spikes.

![Rework 7d](charts/rework-7d.svg)

![Rework 30d](charts/rework-30d.svg)

![Deploy 7d](charts/deploy-7d.svg)

![MTTR 7d](charts/mttr-7d.svg)

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
| Lead (median) | **n/a** | Sample count: 5. Often synthetic when transcripts lack wall clocks. |
| Deploy | **~8.7 / day** (61 merges) | Rises with how often you work; `gh search` may cap at 100. |
| MTTR (median) | **n/a** | Sample count: 7. |
| Rework | **16.7%** (4 / 24) | **Main number to drive down.** Elite &lt; 15%. |
| Post-merge fail | **0.0%** | Reported only — fix-forward; not gated. |


### Last 30 days

| Metric | Value | Notes |
| --- | --- | --- |
| Lead (median) | **n/a** | Sample count: 5. Often synthetic when transcripts lack wall clocks. |
| Deploy | **~2 / day** (61 merges) | Rises with how often you work; `gh search` may cap at 100. |
| MTTR (median) | **43366 s** | Sample count: 14. |
| Rework | **57.4%** (27 / 47) | **Main number to drive down.** Elite &lt; 15%. |
| Post-merge fail | **0.0%** | Reported only — fix-forward; not gated. |


## How rework is counted (v2)

A started execution “fails” (counts in the numerator) if **either**:

1. **Session thrash** — same flags as `reflect-on-thrash` (including `intervention-must-automate`), or
2. **Git path-churn** — ≥3 commits within 24h that overlap the same path(s), optionally paired to a session via Write/Edit paths + workspace/cwd / `CATSTACK_DORA_GIT_ROOTS`.

```text
rework_rate = failed_executions / started_executions
```

## Refresh (weekly job)

```bash
python3 skills/reflect/scripts/publish_dora_snapshot.py --dry-run
# opt-in schedule: ./install.sh --with-dora-snapshot
```

History always records the measurement. `dora-ai.json` updates only when every gated metric is equal or better (`check_dora_baseline.py --check-update`).
