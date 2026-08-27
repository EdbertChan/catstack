`disable-model-invocation: true` means the model never reads this
skill's `description:` to decide whether to apply it -- that text isn't
even loaded into context. The only way this skill activates is an
explicit `/principle-name-the-scorer` invocation.

User: "Our historical-case tag weights just went up for 'late filing' --
does that mean the hand-authored theme priority for late filings should
go up too?" Before answering, the agent explicitly invokes
`/principle-name-the-scorer` to load the full principle.

This skill fires here specifically because of that explicit invocation
-- a question asking whether one of two intentional scorers sets the
other is exactly the pattern the skill targets once loaded (name which
scorer produced which number, say no unless the actual wiring is
shown), but no amount of matching prose alone would have triggered it.
