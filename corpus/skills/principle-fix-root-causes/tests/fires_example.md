`disable-model-invocation: true` means the model never reads this
skill's `description:` to decide whether to apply it — that text isn't
even loaded into context. The only way this skill activates is an
explicit `/principle-fix-root-causes` invocation.

A background job "fails after every restart" with a null-pointer
crash. The proposed fix is to add `if value is None: return` right
before the crash site, so the job no longer throws. Before applying
that fix, the agent explicitly invokes `/principle-fix-root-causes` to
load the full principle.

This skill fires here specifically because of that explicit invocation
— a nil-check guard silencing a crash, plus "fails after restart"
pointing at stale state, is exactly the pattern the skill targets once
loaded (reproduce first, ask why until the root cause is found), but
no amount of matching prose alone would have triggered it.
