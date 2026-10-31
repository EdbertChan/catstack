`disable-model-invocation: true` means the model never reads this
skill's `description:` to decide whether to apply it. cat-mode applies
only when the `CATSTACK_CAT_MODE_DEFAULT=on` hook fires, or on an
explicit `/cat-mode` invocation. Here the hook is on.

The user writes: "open the artifacts for me in chrome". The agent runs
`open -a "Google Chrome" https://claude.ai/artifact/abc` and names the URL.

User: open the artifacts for me in chrome
Assistant: Opened https://claude.ai/artifact/abc in Chrome.

This rule stays silent. The link is open in the browser and the reply names it.
