A user asks for a new tool that spans several files, and the main agent is
about to hand a fork an implementation brief that says "write the scripts" and
never names the language or the mechanism. A shell script that moves existing
functions, a Python package, and re-running the platform's own build are all
live options, and the brief weighs none of them.

This skill fires. Choosing the language or mechanism for a new multi-file tool
is a decision that is expensive to reverse: thousands of lines get built on the
first pick before anyone asks whether another one fit. A brief to a fork that
names no approach is the same trigger, because the fork will pick one silently.
Step 1 states what is chosen and why it is costly to undo, Step 3 labels each
option `considered` or `invented`, and Step 4 sends an `invented` leading option
to `spike-and-validate` before the brief goes out.
