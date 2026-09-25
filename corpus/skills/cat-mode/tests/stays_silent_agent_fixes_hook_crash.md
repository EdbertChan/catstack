`disable-model-invocation: true` means the model never reads this
skill's `description:` to decide whether to apply it. cat-mode applies
only when the `CATSTACK_CAT_MODE_DEFAULT=on` hook fires, or on an
explicit `/cat-mode` invocation. Here the hook is on.

The same Stop hook crashes after a reply. Without being asked, the
agent reads `~/.cache/catstack-hook-metrics/runs.jsonl`, finds the row
for the failing hook with its non-zero exit and traceback, opens the
hook's source, reproduces the crash with the recorded input, and fixes
the crash. Its reply says which hook broke, why, and that the fix is
in, with the failing and passing runs pasted.

This rule stays silent. The agent noticed the crash and owned it; the
user never had to report anything.
