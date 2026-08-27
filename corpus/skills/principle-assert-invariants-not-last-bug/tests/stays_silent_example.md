A user reports a typo in a UI label ("Continu" should be "Continue") and
asks for it to be fixed. The fix is a one-line string change in a single
component.

This skill should NOT fire: there is no class of bug here, no invariant
being violated, and no prior narrower fix that only patched one instance
of a repeating shape. A near-miss on the surface ("a fix for one specific
thing") but not the pattern this skill targets, since there's no general
rule being under-enforced.
