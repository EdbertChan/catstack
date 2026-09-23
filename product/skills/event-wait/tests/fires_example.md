# Should fire

> I kicked off twelve workflow runs. Block until each one finishes and tell me
> which failed — and stop asking for status in a loop, subscribe to the events
> the build already pushes.

Why this fires: the ask is to wait for background workflow and build runs to
complete, many at once, driven by pushed events rather than repeated status
polling. That is exactly the wait this skill owns.

Also fires:

> Wait for the continuous integration run on this branch to finish, then wake
> this session so I do not have to sit here watching it.
