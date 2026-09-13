The user points out that the agent ignored a direct instruction to undo a
change. The agent replies, "You're right: I did not follow that instruction,"
then marks the undo task done even though no revert, check run, fix, or task id
exists and the original change is still present.

This skill fires because the admission became the end of the turn. The agent
named the fault but did not carry a same-reply action that would stop the
bad state from moving forward.

Once loaded it supplies the obligations: name the old claim alongside the new
one rather than switching silently, say what made the first claim unchecked,
treat the admission as a `reflect` trigger, and name the action taken in the
same reply.

A reply that says "I did not follow that instruction" and then only records
"undo done" without doing the undo is still an unfinished correction.
