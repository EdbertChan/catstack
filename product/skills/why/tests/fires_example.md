A user is cleaning up a retry helper and asks: "why is the retry limit set
to five? does that reason still hold, or can I raise it?"

This skill fires. It is a rationale question about an existing constant, not
a behavior question, and it precedes a change — the skill's stated trigger.
Step 1 anchors inline with `git blame -L` on the constant, `git log
--oneline` for the PR number, and `gh pr view` on the merge commit before
any subagent spawns. Step 2 fans out one investigator per source actually
available here, and a source with no MCP gets a null row plus a written
reason rather than being dropped. The report separates what the record says
from what is inferred, and Step 4 converts the answer into
Preserve / Change / Avoid / Risk for the edit that follows.
