`disable-model-invocation: true` means the model never reads this
skill's `description:` to decide whether to apply it -- that text isn't
even loaded into context. The only way this skill activates is an
explicit `/principle-no-lookahead` invocation.

The agent has loaded a full price series into one dataframe and computed a
volume-spike z-score column over the whole thing -- the mean and standard
deviation in every row's denominator are taken across all bars, including
bars that come after that row. It is about to score an entry decision at
each past bar against that column and report the annualised return, which
came out at 41% with no losing month in the span. Before reporting the
number, the agent explicitly invokes `/principle-no-lookahead` to load the
full principle.

This skill fires here specifically because of that explicit invocation
-- a feature computed over the full history and then credited to a
decision at an earlier bar is exactly the pattern the skill targets once
loaded (record what each input is about and when it became knowable, run
the truncation test at ten cut points and compare against the full-history
column, treat a no-losing-month span as a bug report rather than a result),
but no amount of matching prose alone would have triggered it.
