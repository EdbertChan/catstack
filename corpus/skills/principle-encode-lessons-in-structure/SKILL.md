---
name: principle-encode-lessons-in-structure
description: "Apply when you catch yourself writing the same instruction a second time, or notice a recurring correction. Encode the rule as a lint, metadata flag, runtime check, or script instead of more text."
disable-model-invocation: true
---

# Encode Lessons in Structure

Encode recurring fixes in mechanisms (tools, code, metadata, automation) instead of textual instructions. Every error, human correction, and unexpected outcome is a learning signal. Capture it, route it, and close the loop.

**Why:** Textual instructions are easy to miss. They require the reader to notice, remember, and comply. Structural mechanisms (lint rules, metadata flags, runtime checks, automation scripts) enforce the rule without cooperation.

**Pattern:**
When you catch yourself writing the same instruction a second time:
1. Ask: can this be a lint rule, a metadata flag, a runtime check, or a script?
2. If yes, encode it. Delete the instruction
3. If no (genuinely requires judgment), make the instruction more prominent and add an example of the failure mode

**Pick the strongest rung.** When more than one mechanism would work, choose the strongest the situation allows (an unrepresentable state that cannot compile, then a lint or banned API that fails CI, then a canonical helper, then a runtime check), because agents copy whatever the surrounding code already does and a weaker guard becomes the next template.

**Corollary:** Don't paper over symptoms. If the fix is structural, ONLY use the structural fix. The instruction IS the symptom.

**Feedback loop:**
- **Capture every correction.** When the human intervenes or tests fail, decide if it's a one-off or a pattern.
- **Route to the right layer.** One-off -> brain note. Recurring fix -> skill or lint rule. Systemic issue -> principle.
- **Close the loop.** Don't just record. Apply now or create a concrete todo.

**Anti-patterns:**
- Acknowledging without recording ("I'll keep that in mind" does not persist)
- Recording without routing (a brain note about a lint rule that should exist is wasted unless the lint rule gets implemented)
- Fixing without generalizing (fixing one instance while leaving the recurring pattern intact)

**Battle-tested:** The same stale-doc correction was independently rediscovered twice in one day, in two unrelated sessions, before the real fix landed three weeks later — and even then, the fix was another text edit, not a mechanism tying the doc's claim to the code behind it. A textual correction that recurs is exactly the signal this skill names; catching yourself making it a second time (even in a different session) is the trigger, not just noticing it inside one conversation.

**Where a mechanical check is realistic:** only for claims narrow enough to carry a machine-checkable anchor — a doc line that names a specific behavior can require a comment or test filename it points to, so if that anchor's source changes, the doc line gets flagged as stale. The pattern that generalizes: `scripts/validate-pr-body.mjs` fails CI on a PR that claims visual verification but has no literal "Manually inspected:" line — structural because it checks for a marker string, not judged content. Most prose-level corrections don't reduce this cleanly; that half stays a judgment call.
