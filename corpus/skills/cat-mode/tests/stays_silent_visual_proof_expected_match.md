`disable-model-invocation: true` means the model never reads this
skill's `description:` to decide whether to apply it. cat-mode applies
only when the `CATSTACK_CAT_MODE_DEFAULT=on` hook fires, or on an
explicit `/cat-mode` invocation. Here the hook is on.

The Review Claim is about a Slack-thread UI change. Before capture the
agent writes Expected surface (the Slack thread) and Expected
predicates (what must be visible / must not appear). It then captures
that Slack thread's pixels from the live surface — not a mock HTML UI,
not a generated text slide — reads the image, and writes
`Manually inspected:` that walks claim↔pixels against the Expected
list.

This skill's Visual Proof authenticity rules stay silent: surface
matches claim, Expected was declared before capture, the artifact is
real pixels from that surface, and inspection checked the Expected
predicates.
