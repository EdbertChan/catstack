`disable-model-invocation: true` means the model never reads this
skill's `description:` to decide whether to apply it. No explicit
`/cat-mode` invocation happens in this session, and `CATSTACK_CAT_MODE_DEFAULT`
is unset.

The same worker queue drops the newest item under load. The agent has
only seen one user report and has not reproduced the drop, has not
traced it to a specific enqueue call, and has not run any one-variable
control — it has a hypothesis ("probably the queue cap") and nothing
else. Before doing any of that, the agent starts searching Semantic
Scholar for "queue overflow drop" and drafts a citation into the PR
description to back the still-unproved guess.

This skill's literature-research gate stays silent here — not because
the agent is technically prevented from typing a search query, but
because the sequence this bullet names never reached its own gate: a
hypothesis and a single symptom report is not a proved root cause, so
"research literature" was never an open phase, and citing a paper to
support a guess is exactly the citation-dropped-into-prose failure mode
the record requirement exists to catch. The correct next step is
reproduce and trace, not search.
