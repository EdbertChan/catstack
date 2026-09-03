Grading board result: "NEEDS_WORK — the precheck flagged a missing
negative test for the new detector."

This should fire immediately, no re-prompt needed: reflect why it
shipped without the negative test, fix the class of bug (not just this
one detector), codify the invariant in the relevant skill, add a
mechanical catch, then re-run the board.

The "step 3 without step 2" case is caught by
`scripts/check_codify_has_code.py`; see tests/test_codify_has_code.py for the real PR #89 hunk.
