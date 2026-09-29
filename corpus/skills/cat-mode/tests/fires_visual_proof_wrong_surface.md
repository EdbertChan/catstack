`disable-model-invocation: true` means the model never reads this
skill's `description:` to decide whether to apply it. cat-mode applies
only when the `CATSTACK_CAT_MODE_DEFAULT=on` hook fires, or on an
explicit `/cat-mode` invocation. Here the hook is on.

The Review Claim is about a Slack-thread UI change. The agent never
writes Expected surface or Expected predicates. It captures a Claude
(or OpenAI) provider login page, uploads that image as Visual Proof,
and writes a marker-only `Manually inspected:` line with no claim↔pixels
check against any Expected list.

This rule fires. The Visual Proof surface does not match the Review
Claim surface, Expected predicates were never declared before capture,
and a marker-only inspection line is not a check. The correct next
step is declare Expected surface + predicates for the Slack thread,
capture that thread's pixels, then inspect against the Expected list.
