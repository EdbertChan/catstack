---
name: principle-foundational-thinking
description: "Apply before writing logic: choosing core types and data structures, sequencing scaffold-vs-feature work, asking what concurrent actors share. Get the data structures right so downstream code becomes obvious."
disable-model-invocation: true
---

# Foundational Thinking

**Structural decisions** protect option value. **Code-level decisions** protect simplicity. Over-engineering is often a premature decision that closes doors. The right foundational data structure keeps doors open.

**Data structures first.** Get the data shape right before writing logic. The right shape makes downstream code obvious. Define core types early, trace every access pattern, and choose structures that match the dominant paths. A data-structure change late is a rewrite. Early, it is often a one-line diff.

At code level, DRY the structure, not every line. Types and data models should converge. Three similar statements still beat a premature abstraction. Prefer explicit over clever. Test behavior and edge cases, not line counts.

**Concurrency corollary.** Before sharing state between actors, ask "what happens if another actor modifies this concurrently?" If not "nothing", isolate.

**Sequential-composition corollary.** The same ownership question applies with no concurrency at all: before writing a function that calls two different mutators of the same entity in sequence (even on one thread, one call path), ask "can the second mutator run after the first one already finalized this?" A silent `return false` or no-op on an already-terminal state is the tell that nobody owns the transition. Name the owner and make the second call fail loud, not silently no-op.

**Scaffold first.** If something helps every later phase, do it first. Ask "does every subsequent phase benefit from this existing?" CI, linting, test infrastructure, and shared types are scaffold. Sequence for option value: setup before features, tests before fixes. Keep commits small and single-purpose.

Each increment should land a coherent abstraction or deepen one that exists. Do not spread a new capability across callers as special-case coordination.

Subtraction comes before scaffolding: remove dead weight first, then lay foundations.

**Battle-tested:** A dispatch row moves through states like `leased → completed` or `leased → abandoned`. One function (`deferTask`) can terminalize the row on the resource-limit path; a different function later in the *same synchronous call path* (`completeDispatch`) also tries to terminalize it, without checking the first function's outcome. The row silently double-terminates, the caller reads `accepted: false`, and the task resets to pending and re-drains forever — undetected for weeks because nothing about it looked like a concurrency bug. Before writing code where two functions can each finalize the same entity, name who owns the transition, whether or not anything else is running at the same time.
