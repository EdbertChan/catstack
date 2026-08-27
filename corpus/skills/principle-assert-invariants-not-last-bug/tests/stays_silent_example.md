A user reports a typo in a UI label ("Continu" should be "Continue")
and asks for it to be fixed. The fix is a one-line string change in a
single component. No explicit invocation of this skill happens
anywhere in the session — the agent just makes the edit.

This skill stays silent here: with `disable-model-invocation: true`,
nothing about the conversation's content could have triggered it
either way. There is also no class of bug, no invariant being
violated, and no prior narrower fix that only patched one instance of
a repeating shape — even if this skill somehow were invoked, its
content would not apply to a plain one-line typo fix.
