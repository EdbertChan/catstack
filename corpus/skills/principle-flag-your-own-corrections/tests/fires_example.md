Earlier in the session the agent told the user "the stacked slice is fully
green, all gates pass." Checking properly now, the gate it cited had been run
with its default scope and never compared the slice at all — so the green was
vacuous. The agent is about to write the corrected status.

This skill fires on the admission shape itself. It no longer carries
`disable-model-invocation: true`, so its `description:` is loaded and the
model can match it the moment a correction is forming — which is the only
moment it helps. Waiting for an explicit invocation would mean the user has
to notice the stale claim first, which defeats the purpose.

Once loaded it supplies the three obligations: name the old claim alongside
the new one rather than switching silently, say what made the first claim
unchecked (here, a default-scoped command standing in for a slice-scoped
one), and treat the admission as a `reflect` trigger rather than a resolution
to be more careful.

`engine/hooks/wrong-check-reflect` would also catch this particular wording,
but the skill must fire on wordings the hook misses — it stayed silent on "a
claim I made earlier was wrong" in a real session until a human pointed it
out.
