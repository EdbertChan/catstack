# handback-needs-attempt

Stop hook: a reply that asks the user to run a command or perform a step is
judged against the current turn's tool calls and results. It fires when the
agent did not attempt that step first.

It stays silent after a typed permission denial, sandbox or classifier
refusal, or for a step that physically needs the user, such as a password,
OAuth consent, hardware access, or a human-only approval dialog. The meaning
of the reply is defined by
[`handback-needs-attempt.json`](../llm-judge/phrases/handback-needs-attempt.json);
this hook does not use a prose regex.

The hook fails open: it never blocks the outgoing reply. A missing or
unreadable transcript is reported as unchecked, and a judge that cannot
answer is delivered as unchecked through the shared `llm-judge` inbox. The
escape hatch is to name the typed refusal or human-only blocker in the reply.

Tests: `python3 -m unittest discover -s engine/hooks/handback-needs-attempt/tests -v`
