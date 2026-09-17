The agent made a local commit a few minutes ago in this session, has not
pushed it, and wants to drop it with `git reset --hard HEAD~1` before trying
a different approach.

This skill stays silent. Nothing merged is being undone and no earlier
decision is recorded anywhere but this session: there is no PR to read and
no older guard whose reason could be lost. The `history-before-reversal`
hook also stays silent, because `git reset` is not a reversal it checks.
