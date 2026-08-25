---
name: principle-subtract-before-you-add
description: "Apply when sequencing an addition, refactor, or rewrite. Remove dead weight, redundant validators, and stub references first, then build on the simpler base."
disable-model-invocation: true
---

# Subtract Before You Add

When evolving a system, remove complexity first, then build. Deletion gives you a simpler base, which makes the next addition smaller and less brittle.

**Why:** Adding to a complex system compounds complexity. Removing first cuts the surface area, reveals the essential structure, and usually makes the next design obvious. Default to subtraction.

Make simplification a continual investment. Leave the design slightly simpler and more capable behind the same or smaller surface than you found it.

**The pattern:**
- Sequence removal before construction
- Cut before you polish (get to the minimum before investing in quality)
- Design for observed usage, not speculative edge cases
- No speculative validators, parsers, or guards beyond what the spec demands
- Out-of-spec features drag validators behind them. Persistence, retry-on-startup, and schema migration each need guards to defend their inputs.
- Simplify prompts (remove redundant instructions, excessive templates)
- When a reference has no novel content, delete it rather than leaving a stub

**Battle-tested:** A channel-registration bug recurred three times across separate fixes before someone finally chose full de-duplication over "add a completeness check on top of the existing duplicated blocks." The trap: this skill's guidance fires once you're already mid-refactor, but the real decision point is earlier — the moment you're about to patch a symptom on top of code that already duplicates something. Before adding a new handler, worker, or validator, grep for existing implementations of the same responsibility first and explicitly answer "subtract or add?" If this is the second or third time the same duplication has been patched around, that's the signal to stop adding and start removing.
