Assistant has edited `src/auth.ts` four times trying to fix a login bug,
and `token_audit.py`'s output shows `recurring failure signatures: 2` —
the same `TypeError: cannot read property 'sub' of undefined` fired on
attempts 2 and 4, with no test run in between edits 3 and 4.

This is exactly the live, mechanically-evidenced signal the skill exists
to catch: cite the counts plainly ("the same TypeError fired on attempts
2 and 4"), stop guessing at full scope, and offer the user a checkpoint —
narrow to a smaller reproducible slice instead of trying another
full-scope variation.

The same-file-three-edits trigger is mechanical; see
`engine/hooks/narrow-the-scope/tests/fixtures/real_edit_streak_2026-09-01.json` for the real session.
