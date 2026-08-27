User types `/principle-scope-the-session`. A session was opened to fix
a slow query in the analytics-tooling repo; while investigating, the
agent noticed the fleet's disk usage looked odd, dug in, and that
side-investigation turned into a full 20-PR stack landed in a
completely different repo — all inside the same session.

This skill has `disable-model-invocation: true`, so its description is
never loaded into context and never drives auto-triggering — the
explicit `/principle-scope-the-session` invocation above is the only
way it activates. Once invoked: the side-investigation became the real
work and silently displaced the original task. That's the moment to
open a new session scoped to the disk-usage finding, not keep building
in the query-fix session.
