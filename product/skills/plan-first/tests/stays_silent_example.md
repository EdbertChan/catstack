A user reports a typo in one error string and names the file. The agent reads
it, fixes the string, and runs that module's existing test.

This skill stays silent. The work crosses no file, review unit, or commit
boundary, so none of its steps have anything to decide: one claim, one slice,
one obvious gate, and no base-drift risk worth naming. Its own "when this is
worth it" section rules the case out directly — planning a two-line fix costs
more than the fix.

Firing here would produce a Claim/Done-gate/Slices block restating what the
user already said, which is the ceremony this playbook exists to avoid rather
than add.
