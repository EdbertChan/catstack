# Session mine (continuous reflect)

Read this for the opt-in hourly miner that scans Claude, Cursor, and Codex
transcripts for repeated user intervention and emits DORA-for-agents metrics.

## What it does

1. **Mechanical scan** (`cluster_interventions.py`) — extract human user
   utterances, normalize recurring pokes (`make pr`, `commit and push`,
   `/reflect`, …), cluster across sessions, and split each cluster into
   **yes** / **no** circumstance buckets. A cluster with only “always do X”
   and no negative case is incomplete and will not go to headless reflect.
2. **Queue** — write `~/.cache/catstack-session-mine/queue.json` (hashes,
   counts, short quotes, paths). Never full transcripts. Never git.
3. **Headless reflect** — when a cluster is high-confidence (default: 3+
   sessions or 5+ utterances in the window) **and** circumstance-complete
   **and** not on cooldown **and** no open `[auto]` PR for that hash, the
   queue marks it `ready_for_headless`. Interactive `/reflect` still waits
   for chat approval. The worker path treats **GitHub PR review** as the
   approval gate: draft with `draft-pr` headless mode, title prefix
   `[auto]`, include the cluster hash, **never merge**.
4. **DORA-for-agents** (`dora_ai.py`) — optional mechanical events JSON
   produces lead / deploy frequency / MTTR / rework rate / post-merge fail
   rate into `metrics.jsonl`. See clocks below.

## Install (opt-in)

Default `./install.sh` does **not** start scanning. To enable:

```bash
./install.sh --with-session-mine
```

That installs a launchd agent (macOS) that runs hourly:

```bash
python3 "$HOME/.../catstack/skills/reflect/scripts/session_mine.py" run --hours 168
```

Unload with `launchctl unload ~/Library/LaunchAgents/com.catstack.session-mine.plist`
(or re-run install without the flag after removing the plist).

Manual:

```bash
python3 skills/reflect/scripts/session_mine.py run --hours 168
python3 skills/reflect/scripts/session_mine.py report
python3 skills/reflect/scripts/session_mine.py pending
```

## Headless reflect contract

When acting on a `ready_for_headless` cluster:

1. Run reflect steps 1–4 in a subagent on the cluster’s transcript paths
   (aggregate, not every file if huge).
2. Prefer fix hierarchy: hook/test before skill prose.
3. **Repro gate**: every skill/hook/detector change MUST land a positive
   synthetic fixture (detector fires) and a negative fixture (stays
   silent), plus a test. Refuse to open the PR without them — see
   `scripts/check_mine_repro_coverage.py`.
4. Open `[auto]` PR via `draft-pr` headless mode. Call
   `session_mine.py mark-dispatched <hash>` after opening so the weekly
   cooldown starts.
5. Never merge. Never edit live `~/.claude/skills` without a PR.

Interactive `/reflect` is unchanged: present Accepted / Backlog /
Route-to-automate-me / Rejected and wait.

## DORA-for-agents clocks

| Metric | Start | End | Elite | Improve |
| --- | --- | --- | --- | --- |
| Lead (pickup) | plan approved | first mutating tool / Invoker running | &lt; 15 min | down |
| Deploy frequency | — | merged PRs / day | ≥ 2 / day | up |
| MTTR | thrash / path-churn | fix **and** verify pass | &lt; 1 h | down |
| Rework rate | — | thrash\|discard\|**rewrite** / started executions | &lt; 15% | down |

**Rework (fix-forward):** session thrash flags (same thresholds as
`reflect-on-thrash`, including `intervention-must-automate`) **and** git
path-churn — ≥3 commits within 24h that overlap ≥2 paths (or the same path).
Sessions pair to commits via Write/Edit paths + workspace/cwd (Claude project
folder decode, tool cwd) plus optional `CATSTACK_DORA_GIT_ROOTS` (colon-separated
absolute repo roots, e.g. Invoker + catstack).

**Post-merge fail** (revert / hotfix / thrash-after-merge) may still appear in
rollup JSON for curiosity but is **not gated** — this workflow fixes forward.

Committed baseline (aggregates only): [`baselines/dora-ai.json`](../baselines/dora-ai.json)
(version 2+). Plain-English breakdown + charts:
[`baselines/dora-ai-report.md`](../baselines/dora-ai-report.md).
Trend history: [`baselines/dora-ai-history.json`](../baselines/dora-ai-history.json).

Weekly refresh (local; opens a PR, never merges):

```bash
python3 skills/reflect/scripts/publish_dora_snapshot.py --dry-run
./install.sh --with-dora-snapshot   # Mon 9:00 launchd
# optional: rebuild history
python3 skills/reflect/scripts/backfill_dora_history.py --weeks 13
```

```bash
python3 skills/reflect/scripts/capture_dora_baseline.py   # rewrite candidate
python3 scripts/check_dora_baseline.py --current NEW.json --check-update
```

`--check-update` must pass before replacing the committed baseline — every
comparable metric must be equal or better (lead/MTTR/rework down or flat;
deploy frequency up or flat). CI runs `check_dora_baseline.py` to ensure the
baseline file stays well-formed.

Capture sources: local Claude/Cursor/Codex sessions (capped) + local `git log`
path-churn + `gh` merged PRs. No transcript paths in git.

A skill/reflect PR does **not** stop MTTR. Events live in a caller-supplied
JSON list; `session_mine.py run --events FILE` appends a rollup. Rows stay
under `~/.cache` — never commit transcripts or absolute session paths.

## Remote SSH

Hourly heartbeat is **local only**. Remote corpus scan keeps the existing
show-command-then-`--confirm-remote-scan` policy and is not part of launchd.

## Tests

```bash
python3 -m unittest discover -s skills/reflect/scripts/tests -v
python3 scripts/check_mine_repro_coverage.py
```
