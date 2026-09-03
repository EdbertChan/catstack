User types `/principle-push-not-poll`. A session is designing a headless
CLI wrapper that submits a long-running deploy script (10-45 minutes) to
a remote host, then needs to report back when it finishes. The draft
implementation: poll the remote process every 10 seconds in a loop,
re-sending the full accumulated log each time to check for a completion
marker.

This skill has `disable-model-invocation: true`, so its description is
never loaded into context and never drives auto-triggering — the
explicit `/principle-push-not-poll` invocation above is the only way it
activates. Once invoked: this is exactly the described mechanism — a
status-check loop babysitting a long-running background action. The
poll cadence (10s) was picked for responsiveness, not chosen
deliberately, and each check resends the growing log rather than
reading only the delta. The skill's pattern applies directly: prefer a
completion signal (the deploy script writing a done-marker file, or
exiting and being awaited) over a tight poll, and if polling is
unavoidable, widen the interval and cap the check count instead of
polling on a fixed short cadence for an unbounded wait.
