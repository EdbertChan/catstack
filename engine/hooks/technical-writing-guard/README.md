# technical-writing-guard

Stop hook for a document the user asked for. It runs
`product/skills/technical-writing/scripts/grade_prose.py` `sentence_findings`
on the reply, after code fences and inline code are removed.

The grader is looked up in this order: the catstack checkout named on
line 1 of the hook snapshot's `.catstack-source`, then the installed skill
at `~/.claude/skills/technical-writing/scripts` (and the `.cursor` and
`.codex` twins), then three directories above the hook file. The installed
copy of this hook lives under `~/.cache`, so the last walk alone never
finds the grader there.

A hit blocks the turn. Each finding is its own result, so one reply can
report every failed check.

A chat question stays silent. The good rewrite of the skill's own example
stays silent. A banned word that appears only inside backticks stays silent.

A Cursor stop sends a transcript path. Claude sends the reply and may send a transcript for the ask. Codex sends `input-messages` and `last-assistant-message`. Those are read when the plain keys are absent.

A missing user prompt fails open: the turn is allowed. An unreadable reply,
after the user did ask for a document, is unchecked and blocks. A grader
that cannot be imported fails open: the hook logs one `unchecked` row to
the hook metrics and lets the turn through, because a check that never ran
has nothing to say about the reply.

The second stop on the same turn passes, so a rewrite is not graded twice.

Tests: `python3 -m unittest discover -s engine/hooks/technical-writing-guard/tests -v`
