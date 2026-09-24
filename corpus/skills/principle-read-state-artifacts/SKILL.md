---
name: principle-read-state-artifacts
description: "Apply when designing, reviewing, or authoring any mechanism that checks on work a background process already tracks: a babysit/watcher loop, a status check on a queue or worker, an agent verifying what a cron already did. Prefer reading the state artifact the worker already wrote (a ledger, digest, or status file) over re-deriving that state with live commands inside a session transcript."
disable-model-invocation: true
---

# Read the State Artifact, Don't Re-derive It

When a deterministic process already computes and records state, re-computing that state inside a session costs far more than the check itself — every command's raw output lands in the transcript and is re-sent on every later turn.

**Why:** A cron worker that scans a queue every few minutes and appends results to a ledger has already paid for the scan, once, outside any transcript. An agent that re-runs `gh pr list`, `gh pr view`, or a sweep script to learn the same thing pays twice: once for the commands, and again on every subsequent turn that re-sends their accumulated output. The transcript is the bill — a 50-command sweep that adds 500KB of output costs ~500KB of resend per later turn, while reading a folded digest adds a few KB once. The fix is not "check less often"; it is "read what was already computed."

**Pattern:**
- Before writing a watch/babysit loop that checks live state, ask: does a worker, cron, or daemon already record this state? If yes, the loop's read step is a file read or a folded-digest command, not a live query.
- Prefer a state artifact that folds to *latest* state (a digest, a status file, a reduced view) over a raw append-only log — and over re-deriving anything. If only an append-only ledger exists, the right answer is usually a small fold/digest mode on the producer, not each consumer parsing raw history. This skill ships `scripts/fold_jsonl_state.py` as the generic lever: `fold_jsonl_state.py LEDGER.jsonl --by pr,kind,key` folds an append-only JSONL ledger to latest-per-group in one bounded read.
- A consumer that needs one PR's detail queries *that PR* — it does not re-scan the whole queue to find it. Reserve live calls for entries the digest marks as needing action.
- A watcher that only waits for a terminal condition (merged, green, done) should exit when the artifact reports that condition — not keep polling after the answer is final.
- Treat "the session re-ran the scan N times" as a red flag in review, on par with a poll loop: the information was already free elsewhere.

**Battle-tested:** An Invoker `pr-admin-bypass-land` cron worker scanned all admin-bypass PRs every 5 minutes and recorded per-PR dispatch state to `mergify-admin-requeue-state.jsonl` — but babysit agent sessions ignored the ledger and re-derived the same state in-transcript: one 74.6M-token session ran `loop-driver.sh` 55 times and `gh pr view` 59 times across ~20 PRs inside a single run, and a 3.0B-token session spent 5,407 turns re-sending a ~550K-token context built largely of repeated `gh`/`ssh` check output. The fleet-level lesson: tokens ≈ turns × accumulated context, so any check that streams raw scan output into a session multiplies its own cost by the session's remaining lifetime.
