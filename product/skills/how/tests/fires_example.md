A user is about to add a new notification channel and asks: "how does the
dedupe path work before I touch it? is there an n+1 when we look up
subscribers?"

This skill fires. The question is a mechanism question about a subsystem the
agent has not read, asked ahead of an edit — the skill's stated trigger. It
spans more than one file (dedupe plus subscriber lookup), so Step 1 sizes it
broad and Step 2 fans out read-only explorers on non-overlapping angles.
Each returned row carries `read-confirmed` or `name-matched` grounding, and
the merged explanation ends with the mechanism that must still work after
the change — the line `principle-prove-it` will later demand output from.
