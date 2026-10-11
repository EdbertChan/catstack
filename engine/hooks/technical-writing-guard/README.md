# technical-writing-guard

Stop hook for a document the user asked for. It runs
`product/skills/technical-writing/scripts/grade_prose.py` `sentence_findings`
on the reply, after code fences and inline code are removed.

A hit blocks the turn. Each finding is its own result, so one reply can
report every failed check.

A chat question stays silent. The good rewrite of the skill's own example
stays silent. A banned word that appears only inside backticks stays silent.

A Cursor stop sends a transcript path. Claude sends the reply and may send a transcript for the ask. Codex sends `input-messages` and `last-assistant-message`. Those are read when the plain keys are absent.

A missing user prompt fails open: the turn is allowed. An unreadable reply,
after the user did ask for a document, is unchecked and blocks. A missing
grader import is unchecked and blocks.

The second stop on the same turn passes, so a rewrite is not graded twice.

Tests: `python3 -m unittest discover -s engine/hooks/technical-writing-guard/tests -v`
