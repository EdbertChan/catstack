A user asks for a page that shows how much faster merge requests would finish if
a chosen CI job ran faster. The agent is about to write a collector that pulls
job data from the CI system.

This skill fires. The output is something a person will read, so the claim is
not settled until the user has seen it. Before any collection code is planned,
the agent builds a mock page on fake data and asks the user what is shown, what
each number means, and how merge requests are grouped.

The done-gate then names the approved mock, not "the page loads". A collector
built first would answer whatever question the agent guessed, and the user would
only find out after the slow collection run finished. When the plan goes to
Invoker it carries `deliverable: analytics`, so the first task is the approved
mock and every other task depends on it.
