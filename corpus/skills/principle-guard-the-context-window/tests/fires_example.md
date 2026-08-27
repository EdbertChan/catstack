The agent is about to run a shell command that dumps a 4MB CI log straight
to stdout, planning to eyeball the whole thing in the main thread to find
the one failing test.

This is a large payload heading straight into context with no isolation.
The skill should fire: redirect the dump to a file first, `grep`/`jq` only
the relevant lines, or route it to a subagent that reports back a short
verdict instead of the raw 4MB payload.
