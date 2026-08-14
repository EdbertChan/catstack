---
name: principle-scope-the-session
description: "Apply when a session's actual work drifts away from what it was opened to do — a side-investigation becomes the main thread, or an unrelated request gets absorbed into an existing session. Start a fresh session instead of letting scope creep silently expand the one you're in."
disable-model-invocation: true
---

# Scope the Session

A session should end up doing the thing it was opened to do. When the actual work drifts to something else — a side-investigation that becomes the real task, or an unrelated request folded into an existing thread — that drift is a signal to start a new session, not to keep going in the old one.

**Why:** Everything a session already did stays in its context and gets re-billed on every subsequent turn. A session that absorbs a second, unrelated deliverable pays for the first deliverable's full context on every turn of the second one — and blast radius, cost, and learnings all become impossible to attribute cleanly to either task.

**Pattern:**
- If a side-investigation ("let me first check the fleet's disk usage") turns up the real work to do, that's the moment to open a new session scoped to what you just found — not the moment to keep building in the session that happened to discover it.
- If a request arrives that's unrelated to what the current session is doing, and it's substantial enough to need its own review or verification, give it its own session rather than folding it into the current thread's context.
- A worktree or branch name that no longer matches what the session is actually doing is a concrete, checkable signal that scope has drifted.

**Battle-tested:** a corpus retrospective found this twice. One session, nominally in an analytics-tooling project, spent nearly its entire multi-hundred-million-token budget landing an unrelated 20-PR stack in a different repo — the named project got a sliver of the session's budget. Another spanned 29 hours and covered three unrelated deliverables in sequence: an unrelated script request for a different repo, a side-investigation auditing disk usage across several machines, and only then the task its own worktree was named for — which surfaced as a side effect of the disk audit, not as the session's original ask.
