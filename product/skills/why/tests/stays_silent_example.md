A user asks the agent to add a `--json` flag to a CLI command that has no
existing output-format handling, on a file created in this same session.

This skill stays silent. There is no lineage to recover: the code was
written minutes ago in the current session, there is no blame history, no
merged PR, and no prior decision anyone could have written down. Step 1's
anchor commands would return the session's own commit or nothing at all, and
fanning investigators across an issue tracker and team chat for a file that
never existed before today would produce nothing but null rows. The
motivation is in the user's request, already stated.
