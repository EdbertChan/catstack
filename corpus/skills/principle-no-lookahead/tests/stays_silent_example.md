The agent is asked to draw an annotated incident timeline for a postmortem
slide: read the whole quarter of alert history, mark where the outage began,
and label each marker with the cause that was only established afterwards.
The chart reads every row of history, including rows after each marker. No
explicit invocation of this skill happens anywhere in the session -- the
agent just draws the chart.

This skill stays silent here: with `disable-model-invocation: true`,
nothing about the conversation's content could have triggered it either
way. Nothing here is a decision artifact either -- the timeline answers
what happened, not what would I have done, and no score is credited to a
choice made at any marker. A display artifact is allowed to read the whole
history and to move a label back onto the moment the thing really began, so
even if this skill somehow were invoked, its content would not apply until
that chart were fed into an evaluation.
