`disable-model-invocation: true` means the model never reads this
skill's `description:` to decide whether to apply it. cat-mode applies
only when the `CATSTACK_CAT_MODE_DEFAULT=on` hook fires, or on an
explicit `/cat-mode` invocation. Here the hook is on.

The agent proposed two fixes in a chart. One bar is labelled "setup".
The user asks: "so the setup is just the job's prep list? why suggest
it again in fix 1 and 2?" The agent answers with how the prep list
works, then a map of the code that runs it. It never says whether
"setup" in the fix rows is the existing step or a new one.

User: so the setup is just the job's prep list? why suggest it again in fix 1 and 2?
Assistant: The prep list runs secrets, clone, and repo sync, then the build script calls the packager...

This rule fires. A term inside a proposal is placed first: the first
sentence says whether it already exists or is being added.
