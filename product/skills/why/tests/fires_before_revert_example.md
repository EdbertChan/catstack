The merge queue is red because a database check rejects rows that a
recently merged PR now writes. Undoing that PR makes the check pass, and the
agent is about to run `git revert <sha>`.

This skill fires, as the research step before a reversal. The parent spawns
one read-only decision-history investigator with the SHA and the failing
check's error text. The investigator quotes the merged PR's claim, runs
`git log -S` on the error text, finds and quotes the older PR that added the
check, and reports merge dates, each row read-confirmed with its ref. The
parent sees that the check predates the newer PR's stated intent, so the
check is the stale side and the fix goes forward instead of reverting. Had a
reversal still been right, the parent would name the reversed PR and ask
before undoing merged work.
