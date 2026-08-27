A background job "fails after every restart" with a null-pointer crash.
The proposed fix is to add `if value is None: return` right before the
crash site, so the job no longer throws.

This skill should fire: this is a classic symptom fix (a nil-check guard
silencing a crash) instead of tracing why the value is None in the first
place. The skill's pattern is to reproduce first, ask "why" until the root
cause is found, and specifically resist adding guards that just silence
the crash — plus "fails after restart" should prompt suspecting stale
persistent state, not the code.
