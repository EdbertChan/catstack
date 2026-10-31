`disable-model-invocation: true` means the model never reads this
skill's `description:` to decide whether to apply it. cat-mode applies
only when the `CATSTACK_CAT_MODE_DEFAULT=on` hook fires, or on an
explicit `/cat-mode` invocation. Here the hook is on.

The agent finds the owner from commit authors and says why. It drafts one
yes/no question tied to the user's goal. When the reply is pasted, it opens
with the verdict.

User: here is his reply
Assistant: Not stated. He did not say whether he needs the package. Still open: whether the job that uses it is live. Next question: "Does your job still call this package after the migration?"

This rule stays silent. The owner came from data, and the reply opens with
yes, no, or not stated, then what is open, then the next question.
