`disable-model-invocation: true` means the model never reads this
skill's `description:` to decide whether to apply it -- that text isn't
even loaded into context. The only way this skill activates is an
explicit `/principle-guard-the-context-window` invocation.

The agent runs `ls -la` and gets a few dozen short lines back. No
explicit skill invocation happened. The capture helper may still wrap
the shell call when the hook is installed, and under the body cap the
stub includes the small stdout — that is fine and is not this skill
firing. Without `/principle-guard-the-context-window`, this skill stays
silent.
