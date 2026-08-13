---
name: principle-outcome-oriented-execution
description: "Apply whenever a change threads a new required value through existing callers, not just named rewrites/migrations — a new required field, a new parameter, a new required IPC/API argument. Converge on the target shape in one slice; don't preserve smooth intermediate states with throwaway compatibility code."
disable-model-invocation: true
---

# Outcome-Oriented Execution

Optimize for the intended, verifiable end state rather than preserving smooth intermediate states.

**Why:** Keeping every intermediate step fully stable often creates temporary compatibility code that becomes long-lived debt. Converge on the target architecture and prove correctness at explicit verification boundaries.

**Core rule:**
- Prioritize end-state integrity over transitional stability
- Intermediate breakage is acceptable when it is planned, scoped, and reversible
- Always run final verification before declaring done

**Guardrails:**
- Use this for planned rewrites and migrations with explicit phase boundaries — and for small changes too: a new required field, a new IPC argument, a new parameter threaded through a pipe are migrations at small scale, not exceptions
- Declare where temporary breakage is acceptable
- Keep high-signal checks for actively touched areas while migrating
- Require full static and runtime verification at plan completion

**Battle-tested:** You're threading a new required field through an existing pipe (an IPC message, a stream sequence, a function signature). The tempting shape is three PRs: add the field as optional with a fallback ("compat shim"), wire callers to use it, then delete the fallback later. Each PR reviews clean, but the fallback ships to production and can outlive its intended lifetime — a real 3-PR stack did exactly this, with one PR literally titled "compat shim." Add the field, wire every caller, and delete the fallback in the same slice. There should be no window where "optional + fallback" is the shipped state, no matter how small the change looks.
