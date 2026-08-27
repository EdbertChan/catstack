The agent kicks off an overnight CI-repair loop that will poll a build
queue every 15 minutes for the next 6 hours, resuming the same growing
session thread each time, with no explicit compaction plan.

Wall-clock idle gaps between polls will each blow past the prompt-cache
TTL, so every resume pays a full-price context rebuild instead of a cheap
cache hit. The skill should fire: decide up front to compact before the
gap, or switch to a detached poller that reports back once instead of
resuming the same thread every 15 minutes.
