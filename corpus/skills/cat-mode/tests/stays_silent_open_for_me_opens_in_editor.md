`disable-model-invocation: true` means the model never reads this
skill's `description:` to decide whether to apply it. cat-mode applies
only when the `CATSTACK_CAT_MODE_DEFAULT=on` hook fires, or on an
explicit `/cat-mode` invocation. Here the hook is on.

The agent has just cited three lines in two files. The user writes:
"open those for me in my code editor". The editor the user named has no
command that opens a file from outside. The agent looks in PATH,
`/Applications` and `~/Applications` once, finds VS Code, and runs
`code -g build.yml:3408 -g packager.sh:10 -g packager.sh:69`.

User: open those for me in my code editor
Assistant: Opened all three in VS Code at their lines. Your editor has no way to open a file from outside, so I used the installed one.

This rule stays silent. Every named file is open at its cited line, and
the one-line note says why a different editor was used.
