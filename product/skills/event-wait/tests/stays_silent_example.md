# Should stay silent

> What is the status of the last build?

Why this stays silent: it is a single question answered by one ordinary
lookup. Nothing has to block, nothing runs concurrently, and there is no
long-running job to attach to. Starting a blocking listener for a one-shot
question would be the wrong shape.

Also stays silent:

> Add a retry to this HTTP client when the server returns 503.

Retrying a request is not waiting on a pushed event, and this skill has no
opinion about it.
