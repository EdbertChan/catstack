User says: "Land PR #482, then #483 once it's merged — they're a stack
on top of main via Mergify."

This is a direct land/merge/queue request for a PR stack, so the skill
applies: resolve PR numbers bottom-up, run the SHA-verified guard before
any write (head SHA in local clone, real stack-branch convention, proper
base chain, all OPEN), then merge bottom-up, re-checking mergeability
after each retarget instead of trusting a stale read.
