User says: "Can you review PR #482 and tell me if the diff looks safe?"

This asks for a review opinion, not to land, merge, ship, or queue
anything — no write action is being requested at all. The skill's hard
rule (never identify a PR to land by branch name, verify by SHA before
any write) has nothing to guard here, since nothing is being merged.
