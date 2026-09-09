A parent agent is about to fan out three explorers to trace a notification
dedupe path, and is writing their prompts. It has not named which files each
explorer may touch, whether they may write, or what to do if one finds the
dedupe logic is not where the brief says it is.

This skill fires at the moment of spawning. It does not carry
`disable-model-invocation: true`, so its `description:` is loaded and the
model can match it on a delegation turn — which is the only useful moment: a
scope boundary stated after the subagent returns is not a boundary. Once
loaded it supplies the four inherited limits (files, write authority,
destructive actions, the question) and the contradiction contract, so an
explorer that finds the brief pointed at the wrong module reports that with a
`file:line` and the ref rather than silently fixing the module it thinks was
meant.
