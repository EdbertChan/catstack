# handback-needs-attempt

A background Claude Stop hook that checks whether the latest reply hands the user a command or agent-doable step that this turn did not attempt. The shared LLM judge receives the reply and the current turn's tool calls and results, so meaning is defined by engine/hooks/llm-judge/phrases/handback-needs-attempt.json, not a phrase-matching regex.

It fires when the judge finds an unattempted hand-back with no earlier permission prompt, sandbox or classifier refusal. A hit is delivered through the shared llm-judge inbox on the next turn with this message:

> handback-needs-attempt: this reply hands a runnable command or agent-doable step back to the user without an attempt in this turn. Attempt it first, or name the permission refusal, sandbox or classifier refusal, or human-only blocker such as a password, OAuth consent, or hardware that means only the user can do it.

It stays silent after an actual attempt, a permission or tool refusal, and a step only the human can complete such as a password, OAuth consent, or hardware action. stop_hook_active returns immediately so a rewritten reply is not re-queued.

Fail direction: an unreadable or missing transcript fails open and reports unchecked on stderr; it never flags from missing evidence. A judge that cannot produce a result is delivered as unchecked, never as clean.

The escape hatch is to attempt the command or step first. If only the user can complete it, name the human-only blocker in the reply.
