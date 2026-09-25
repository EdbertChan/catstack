A user asks the agent to change a log message's wording in one file. The
agent reads the file, makes the single edit, and runs the existing test for
that module itself.

This skill stays silent. No subagent, fork, explorer, or worker is spawned
anywhere in the turn, so there is no scope to inherit and no second actor
whose authority could exceed the parent's. The principle has no target: its
four limits all describe what a delegate may do, and the contradiction
contract describes how a delegate reports back. A single agent editing one
file on its own behalf is the case this principle is not about.

A second silent shape, against the decisions slot. A parent hands an explorer
a read-only brief that names the files, the question, and one settled
decision relayed as a constraint the explorer may not re-open. The explorer
reads those files, answers the question, and reports one contradiction with a
`file:line` and the ref it was read at, leaving the decision alone. Nothing
here is a widening: the boundary was stated, the constraint travelled as a
constraint, and the contradiction went back up rather than being acted on.
