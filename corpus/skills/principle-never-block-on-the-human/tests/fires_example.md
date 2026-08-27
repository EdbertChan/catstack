The agent has just landed 2 of a planned 13-slice PR stack, all local and
uncommitted. It pauses and asks: "Should I keep going? Slices 3 onward
touch riskier code paths." Nothing about this next slice is irreversible —
it's another local, reviewable code change.

Trigger: proceed and present the result instead of asking permission on
reversible work. Reserve the question for an actually irreversible step
(a push, an external send, a production write).
