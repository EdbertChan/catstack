An agent reads `headless.ts:706-715`, sees a per-kind lock file taken before
a worker runs, and writes: "Only one of each kind should run, and a lock file
is the only thing enforcing it (`headless.ts:706-715`)." Nothing searched the
other places a worker can be started.

This skill fires. The cited lines are real and show that one lock exists.
They do not show it is the only guard. A `file:line` backs only what that line
says, so "the only" needs a pasted search over every place a worker starts. In
the incident, that search would have found an in-memory guard in the
controller that refuses a second running copy, and a second command-line tool
that starts its own worker without the lock.

The same shape fires on a count. "24 of the 28 kinds have only one fixture"
needs the listing that counted all 28 pasted next to it. In the incident the
real count was 26, and no listing was ever run.
