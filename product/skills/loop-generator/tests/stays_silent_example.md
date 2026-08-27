User says: "Our integration-test job is flaky, can you look at the logs
and fix the actual race condition causing it?"

This is a one-off diagnose-and-fix request against the current failure,
not a request to build a recurring babysit/watch/retry artifact. There is
no `loop_name`, no target set to rebuild each round, and nothing that
should keep retrying unattended — so no interview or generated
doc/script pair is warranted.
