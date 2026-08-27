The task is: "rename this config key across 40 files, and update every
call site that reads the old name." The agent starts editing files one by
one by hand.

This skill should fire: 40 files is non-trivial bulk work with a clear
mechanical recipe (find the old key, replace with the new one, verify no
call site still reads the old name). A codemod or script should do this
once and be rerunnable/diffable, instead of 40 manual edits a reviewer
can't re-verify without redoing them.
