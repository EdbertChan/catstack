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

A second shape, from the Related section. The parent's brief opens "read-only
investigation" and then, three paragraphs later, tells the subagent to write
the fix it finds. The subagent is about to edit the live checkout, reading the
read-only opening as the prompt's real posture and the write instruction as a
licence to touch the working tree it was already in. The link to
`principle-separate-before-serializing-shared-state` settles it: instructions
and conventions are not concurrency control, so a read-only brief is not
filesystem isolation. A subagent told to write files runs in its own worktree
even when the rest of the prompt defaults to read-only, and the parent that
omitted one has not stated the boundary at all.

A third shape, the one the decisions slot exists for. The user has already
decided which stage a new toggle gates. The parent relays that requirement
word for word and then appends "work out what a toggle would actually gate."
A mechanical containment check on the delegation passes — the requirement is
verbatim-contained and every content word is present — and the subagent still
ranks the user's own requirement fourth of six and argues its premise away.
The skill fires here because the decision was relayed as part of the
question instead of as a settled constraint, and because the anti-priming
rule reads re-opening it as rigour.

No mechanical catch is claimed for that third shape, and the obvious one is
known not to work: the containment check returns PASS on the exact
delegation that drifted, because the words were all there. The gate is the
parent's wording, so this stays an `unchecked` case pinned by prose.
