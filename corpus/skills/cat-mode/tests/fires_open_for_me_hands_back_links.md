`disable-model-invocation: true` means the model never reads this
skill's `description:` to decide whether to apply it. cat-mode applies
only when the `CATSTACK_CAT_MODE_DEFAULT=on` hook fires, or on an
explicit `/cat-mode` invocation. Here the hook is on.

The agent has just cited three lines in two files. The user writes:
"open those for me in my code editor". The agent replies with the three
paths as clickable links and says "Cmd+click to open". It never looks
for an installed editor and never runs a command that opens the files.

User: open those for me in my code editor
Assistant: Cmd+click to open: build.yml:3408, packager.sh:10, packager.sh:69

This rule fires. "Open X for me" asks for the files to be open in the
user's local editor now; a link or a path to click is not opening it.
