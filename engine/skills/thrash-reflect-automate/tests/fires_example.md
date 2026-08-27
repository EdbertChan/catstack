Grading board result: "NEEDS_WORK — the precheck flagged a missing
negative test for the new detector."

This should fire immediately, no re-prompt needed: reflect why it
shipped without the negative test, fix the class of bug (not just this
one detector), codify the invariant in the relevant skill, add a
mechanical catch, then re-run the board.
