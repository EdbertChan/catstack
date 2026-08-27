`disable-model-invocation: true` means the model never reads this
skill's `description:` to decide whether to apply it — that text isn't
even loaded into context. The only way this skill activates is an
explicit `/principle-build-the-lever` invocation.

The task is: "rename this config key across 40 files, and update every
call site that reads the old name." Before starting, the agent
explicitly invokes `/principle-build-the-lever` to load the full
principle.

This skill fires here specifically because of that explicit invocation
— 40 files with a clear mechanical recipe is exactly the pattern the
skill targets once loaded (build a rerunnable codemod instead of 40
manual edits), but no amount of matching prose alone would have
triggered it.
