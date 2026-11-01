User says: "Rename `maybeFlush` to `flushIfDirty` across the writer package
and update its two call sites."

This is a rename with no reported failure behind it. There is nothing to
reproduce, no surface the bug was seen on, no candidate hypotheses to
binary-search, and no original failure to verify a fix against. Working an
eight-step procedure whose first step is a failing run would stall on step one
forever, because no run fails.

Describing a bug in passing is not the trigger either: "The writer used to
drop rows, which is why this name is confusing." That is history, not a bug to
fix now. A reported failure that needs reproducing, bisecting and verifying is
the trigger.
