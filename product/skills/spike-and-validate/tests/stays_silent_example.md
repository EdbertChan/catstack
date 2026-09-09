A user asks why an existing export job writes duplicate rows after a retry.
The behavior is already implemented, already reproducible, and the answer is
in the code.

This skill stays silent. Its own "when not to spike" section rules this out
directly: the answer is in the code, so this is `how`, and the causal
question about an existing defect belongs to the repro-then-fix path in
`principle-fix-root-causes`. There is no untested assumption about something
that does not exist yet, and building a throwaway would not answer a
question the real code already answers.
