User types `/principle-never-block-on-the-human` after landing 2 of a
planned 13-slice PR stack, all local and uncommitted, then pausing to
ask "should I keep going? Slices 3 onward touch riskier code paths."

This skill has `disable-model-invocation: true`, so its description is
never loaded into context and never drives auto-triggering — the
explicit `/principle-never-block-on-the-human` invocation above is the
only way it activates. Once invoked: nothing about the next slice is
irreversible, it's another local, reviewable code change — proceed and
present the result instead of asking permission. Reserve the question
for an actually irreversible step (a push, an external send, a
production write).
