---
name: principle-separate-before-serializing-shared-state
description: "Apply when concurrent actors might write to the same file, branch, key, or state object. Eliminate the sharing first; serialize structurally only when one shared writer is a real invariant."
disable-model-invocation: true
---

# Separate Before Serializing Shared State

When concurrent actors might share mutable state, first ask whether they truly need the same mutable object. If not, eliminate the sharing. When sharing is real, enforce serialization structurally: lockfiles, sequential phases, exclusive ownership. Instructions and conventions are not concurrency control.

**Why:** Concurrent writes to shared state create race conditions that are intermittent, hard to reproduce, and expensive to debug. Telling agents or goroutines to "take turns" does not work.

**Pattern:**
1. **Identify shared mutable state** (files both read and write, branches both push to, APIs both define and consume).
2. **Default: eliminate the shared write target.** Ask: do these actors need one canonical object, or are they publishing independent facts? Give each actor its own owned file, key, branch, or state directory, and merge only at the read/reporting boundary. Two workers writing their own `lastX` field into one `state.json` is still shared mutation; `indexer-state.json` + `metrics-state.json` is not.
3. **Only when one shared write target is a real invariant, serialize access structurally** (lockfiles, sequential phases, single-writer actor, or atomic compare-and-swap). Treat "we need a lock" as a design smell to check, not as the default answer.

**Battle-tested:** Sometimes the sharing genuinely can't be eliminated — a database that loads its whole state into memory and flushes it wholesale has no file to split; every reader and writer needs the same canonical object. A lockfile with stale-lock reclamation is the first fix, but even a well-built lock can still race under retry/reconnect. When it does, escalate past locking to a hard single-owner boundary: the constructor for the shared resource refuses to run without an explicit ownership capability, enforced by a required CI check that rejects any non-owner module importing it writable. That's step 3 done as a real static check, not just a design principle — a genuine shared-write target still gets structural enforcement, not a comment asking people to be careful.
