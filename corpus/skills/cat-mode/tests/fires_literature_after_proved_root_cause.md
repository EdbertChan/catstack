`disable-model-invocation: true` means the model never reads this
skill's `description:` to decide whether to apply it — that text isn't
even loaded into context. cat-mode applies only when the
`CATSTACK_CAT_MODE_DEFAULT=on` hook fires, or on an explicit
`/cat-mode` invocation.

A worker queue silently drops the newest item once it hits 500 pending
jobs. The agent reproduces it on demand (a script that floods the
queue past 500 and shows the drop every time), traces it with logging
to the exact enqueue call, and proves the root cause with a
one-variable control: hard-coding the queue's cap to 5000 makes the
drop disappear on the same repro, and reverting the cap brings the
drop back — fail-before/pass-after, isolated to that one variable,
pasted in the same message.

Only after that proof does the agent open the research phase. It
writes an anonymized mechanism statement — "a bounded FIFO queue
silently drops the newest item on overflow instead of blocking or
erroring" — with no proprietary code or session details in it, hands
that to a read-only subagent to search Semantic Scholar and OpenAlex,
and independently reads the two papers the subagent returns before
citing either. One paper describes the same overflow behavior in a
different system and recommends backpressure over silent drop
(recorded as support); the other studies a different queue discipline
entirely and is recorded as read, not applicable. The agent then
chooses backpressure as the intervention and re-verifies the fix with
the same probe script.

This skill fires here specifically because the gated sequence was
followed in order — repro, trace, proved root cause with an isolated
control — before the literature step ever opened, the mechanism
statement was anonymized before anything left the machine, and every
source got a support/contradiction/applicability record instead of a
citation dropped into prose.
