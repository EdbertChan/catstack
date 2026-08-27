A session was opened to fix a slow query in the analytics-tooling repo.
While investigating, the agent notices the fleet's disk usage looks odd,
digs in, and that side-investigation turns into a full 20-PR stack
landed in a completely different repo — all inside the same session.

Trigger: the side-investigation became the real work and silently
displaced the original task. That's the moment to open a new session
scoped to the disk-usage finding, not keep building in the query-fix
session.
