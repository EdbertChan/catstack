`disable-model-invocation: true` means the model never reads this
skill's `description:` to decide whether to apply it. cat-mode applies
only when the `CATSTACK_CAT_MODE_DEFAULT=on` hook fires, or on an
explicit `/cat-mode` invocation. Here the hook is on.

The agent finishes a reply. A Stop hook then crashes with a Python
traceback, and the harness shows `Stop hook error` under the reply. On
its next turn the agent writes: "I see a hook error at the bottom —
did a hook fail on your side? Can you paste the full error so I can
look?" It never opened `runs.jsonl`, never read the hook's stderr, and
never looked at the hook's source.

This rule fires. The crash was already recorded where the agent could
read it, so asking the user to report it hands the agent's own job
back to them. The correct next step is to read the hook log, find the
failing hook, and fix it.
