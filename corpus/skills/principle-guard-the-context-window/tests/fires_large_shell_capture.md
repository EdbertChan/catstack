`disable-model-invocation: true` means the model never reads this
skill's `description:` to decide whether to apply it -- that text isn't
even loaded into context. The only way this skill activates is an
explicit `/principle-guard-the-context-window` invocation.

The agent is about to run `gh run view 33367716576 --repo owner/repo --job 99412013915 --log`
and paste the whole job log into the parent thread. Before running it, the
agent explicitly invokes `/principle-guard-the-context-window`.

This skill fires because of that explicit invocation: run the capture
helper, keep full bytes on disk, and if the stub is over the parent body
cap, spawn a fresh read-only subagent with the artifact path and a
specific question. Do not FAIL-grep in the parent or Read the artifact
unbounded.
