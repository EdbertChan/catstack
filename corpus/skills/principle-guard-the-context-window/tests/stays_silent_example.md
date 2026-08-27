The agent reads a single 40-line config file to check one setting, then
moves on to editing it. No explicit invocation of this skill happens
anywhere in the session.

This skill stays silent here: with `disable-model-invocation: true`,
nothing about the conversation's content could have triggered it
either way. There is also no 200KB+ payload, no third redundant read,
and no oversized skill load -- even if this skill somehow were invoked,
its content would not apply to one small, necessary, targeted read.
