`disable-model-invocation: true` means the model never reads this
skill's `description:` to decide whether to apply it. cat-mode applies
only when the `CATSTACK_CAT_MODE_DEFAULT=on` hook fires, or on an
explicit `/cat-mode` invocation. Here the hook is on.

The agent has just named a CI pipeline by its id. The user writes:
"open the gitlab link for 44024335 for me". The agent replies with the bare
id and never runs a command that opens a page in a browser.

User: open the gitlab link for 44024335 for me
Assistant: That is pipeline 44024335.

This rule fires. A URL opens in the user's browser, and an id with no link is
not opening anything.
