A user asks to bump a timeout constant from 30 to 60 seconds in a file they
are currently looking at, and pastes the line. The agent makes the one-token
edit.

This skill stays silent. There is no mechanism to trace: the target is a
single literal in a file already in context, the user supplied the code, and
nothing about the change depends on understanding a call path. Step 1 would
size this narrow and the skill's own "do not" list rules out fanning
subagents at a question one file answers. Running `how` here would spend
subagents to re-explain a line the user just read.
