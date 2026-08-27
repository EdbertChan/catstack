Earlier in the session the agent told the user "this test suite has 71
tests and they all pass." Later, running the suite for real shows only 68
tests exist and one of the earlier 71 was double-counted due to a bug in
the counting script.

This skill should fire: a fact already stated to the user (71 tests) turned
out to be wrong. The next message that touches the test count must say
"earlier I said 71, that was wrong — it's actually 68," not just start
quietly citing 68 as if it had always been the number.
