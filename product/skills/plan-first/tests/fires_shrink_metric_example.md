The user asks for a plan to shrink a log database that has grown past its
disk budget, across a reaper script, its schedule, and a retention config.

This skill fires, and the claim is a shrink claim, so Step 1 names the metric
and measures it on real data before the first edit: the file size on disk and
the row count per age bucket, read from the real database, not from a fixture.
That measurement is what tells a change that helped from one that didn't.

Here it changes the plan. The real rows are all newer than the retention cut,
so the reaper the user asked for would prune 0 of them; and SQLite does not
return freed pages to the filesystem, so the file would not shrink without a
follow-up `VACUUM` slice. Both are knowable before the diff. Without the
measurement the first PR stack ships a reaper that moves the metric zero, and
a second stack has to go fix what the first one didn't move.
